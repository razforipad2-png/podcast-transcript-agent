"""TranscriberAgent: download an audio file and transcribe it with OpenAI Whisper.
Large files (> 25 MB) are split into chunks with pydub before sending.
"""
import os
import re
import tempfile

import requests
from openai import OpenAI
from pydub import AudioSegment

import config
from tools.transcript import validate_and_score

_AUDIO_EXTS       = re.compile(r'\.(mp3|m4a|ogg|wav|aac|opus|flac|mp4|webm)(?:\?|$)', re.IGNORECASE)
_SIZE_LIMIT       = 24 * 1024 * 1024   # stay under Whisper's 25 MB hard limit
_CHUNK_MS         = 4 * 60 * 1000      # 4-minute chunks
_DOWNLOAD_TIMEOUT = 180                 # seconds


def _ext_from_url(url: str) -> str:
    m = _AUDIO_EXTS.search(url)
    return ("." + m.group(1).lower()) if m else ".mp3"


class TranscriberAgent:
    def __init__(self):
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)

    def run(self, audio_url: str) -> dict:
        """
        Download audio_url and transcribe with whisper-1.
        Files > 25 MB are split into 10-minute chunks automatically.
        Returns: {success, transcript_text, confidence, error}
        """
        ext      = _ext_from_url(audio_url)
        tmp_path = None
        try:
            resp = requests.get(
                audio_url, timeout=_DOWNLOAD_TIMEOUT, stream=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()

            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = tmp.name
                for chunk in resp.iter_content(chunk_size=65_536):
                    tmp.write(chunk)
        except Exception as e:
            self._cleanup(tmp_path)
            return self._fail(str(e))

        try:
            file_size = os.path.getsize(tmp_path)
            if file_size > _SIZE_LIMIT:
                print(f"Audio is {file_size // (1024*1024)} MB — splitting into chunks")
                text = self._transcribe_chunked(tmp_path, ext)
            else:
                text = self._transcribe_file(tmp_path)
        finally:
            self._cleanup(tmp_path)

        if text is None:
            return self._fail("Transcription failed")
        if not text:
            return self._fail("Whisper returned an empty transcript")

        _, confidence = validate_and_score(text)
        return {
            "success":         True,
            "transcript_text": text,
            "confidence":      confidence,
            "error":           None,
        }

    # ------------------------------------------------------------------

    def _transcribe_file(self, path: str) -> str | None:
        try:
            with open(path, "rb") as f:
                result = self.client.audio.transcriptions.create(
                    model="whisper-1", file=f,
                )
            return result.text
        except Exception as e:
            print(f"Whisper error: {e}")
            return None

    def _transcribe_chunked(self, path: str, ext: str) -> str | None:
        fmt = ext.lstrip(".")
        try:
            audio = AudioSegment.from_file(path, format=fmt)
        except Exception as e:
            print(f"pydub failed to load audio: {e}")
            return None

        parts = []
        for start_ms in range(0, len(audio), _CHUNK_MS):
            chunk     = audio[start_ms : start_ms + _CHUNK_MS]
            chunk_tmp = None
            try:
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                    chunk_tmp = f.name
                chunk.export(chunk_tmp, format=fmt)
                text = self._transcribe_file(chunk_tmp)
                if text:
                    parts.append(text)
                    print(f"  chunk {len(parts)} transcribed ({start_ms // 60000}–{(start_ms + _CHUNK_MS) // 60000} min)")
            finally:
                self._cleanup(chunk_tmp)

        return " ".join(parts) if parts else None

    def _fail(self, error: str) -> dict:
        return {"success": False, "transcript_text": None, "confidence": None, "error": error}

    def _cleanup(self, path: str | None) -> None:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
