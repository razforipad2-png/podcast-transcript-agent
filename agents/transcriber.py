"""TranscriberAgent: download audio and transcribe with OpenAI Whisper.
Large files are split into raw byte chunks without loading into memory.
"""
import os
import re
import tempfile

import requests
from openai import OpenAI

import config
from tools.transcript import validate_and_score

_AUDIO_EXTS       = re.compile(r'\.(mp3|m4a|ogg|wav|aac|opus|flac|mp4|webm)(?:\?|$)', re.IGNORECASE)
_SIZE_LIMIT       = 24 * 1024 * 1024   # 24 MB — Whisper hard limit
_CHUNK_SIZE       = 20 * 1024 * 1024   # 20 MB chunks
_DOWNLOAD_TIMEOUT = 180


def _ext_from_url(url: str) -> str:
    m = _AUDIO_EXTS.search(url)
    return ("." + m.group(1).lower()) if m else ".mp3"


class TranscriberAgent:
    def __init__(self):
        self.client = OpenAI(api_key=config.OPENAI_API_KEY)

    def run(self, audio_url: str) -> dict:
        ext = _ext_from_url(audio_url)
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
                print(f"Audio is {file_size // (1024*1024)} MB — splitting into raw chunks")
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

    def _transcribe_file(self, path: str) -> str | None:
        try:
            with open(path, "rb") as f:
                result = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    response_format="verbose_json"
                )
            return "\n\n".join(seg.text.strip() for seg in result.segments)
        except Exception as e:
            print(f"Whisper error: {e}")
            return None

    def _transcribe_chunked(self, path: str, ext: str) -> str | None:
        parts = []
        chunk_num = 0
        with open(path, "rb") as f:
            while True:
                data = f.read(_CHUNK_SIZE)
                if not data:
                    break
                chunk_num += 1
                chunk_tmp = None
                try:
                    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as cf:
                        chunk_tmp = cf.name
                        cf.write(data)
                    print(f"  transcribing chunk {chunk_num} ({len(data) // (1024*1024)} MB)")
                    text = self._transcribe_file(chunk_tmp)
                    if text:
                        parts.append(text)
                        print(f"  chunk {chunk_num} done")
                finally:
                    self._cleanup(chunk_tmp)
        return " ".join(parts) if parts else None

    def _fail(self, error: str) -> dict:
        return {"success": False, "transcript_text": None, "confidence": None, "error": error}

    def _cleanup(self, path) -> None:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass
