import os
import re
import datetime

import config
from agents.researcher import ResearcherAgent
from agents.extractor import ExtractorAgent
from agents.cleaner import CleanerAgent
from agents.transcriber import TranscriberAgent
from tools.rss import find_audio_url
from tools.transcript import CONF_RANK

_YT_URL_RE  = re.compile(r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+', re.IGNORECASE)
_SLUG_RE    = re.compile(r'[^\w\s-]')
_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'output')


def _slugify(text: str) -> str:
    return _SLUG_RE.sub('', text).strip().replace(' ', '_')


def _make_filename(input_data: dict) -> str:
    if input_data.get("mode") == "search":
        show    = _slugify(input_data.get("show", "unknown"))
        episode = _slugify(input_data.get("episode", "unknown"))
    else:
        url  = input_data.get("url", "")
        slug = _slugify(re.sub(r'https?://', '', url)[:60])
        show, episode = slug, "transcript"
    return f"{show}_{episode}_transcript.txt"


def _save_transcript(filename: str, input_data: dict, source: str, confidence: str, text: str) -> str:
    today = datetime.date.today().isoformat()
    show    = input_data.get("show") or input_data.get("url", "")
    episode = input_data.get("episode", "")

    header = (
        f"Show: {show}\n"
        f"Episode: {episode}\n"
        f"Source: {source}\n"
        f"Retrieved: {today}\n"
        f"Confidence: {confidence}\n"
        f"---\n\n"
    )

    path = os.path.join(_OUTPUT_DIR, filename)
    os.makedirs(_OUTPUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + text)
    return path


def _find_youtube_url(input_data: dict, research: dict) -> str | None:
    url = input_data.get("url", "")
    if _YT_URL_RE.search(url):
        return url
    audio_url = research.get("audio_url") or ""
    if _YT_URL_RE.search(audio_url):
        return audio_url
    for entry in research.get("tried", []):
        m = _YT_URL_RE.search(entry)
        if m:
            return m.group(0)
    return None


def _pick_best(research: dict, extraction: dict | None) -> tuple[str | None, str | None, str | None]:
    r_conf = CONF_RANK.get(research.get("confidence"), 0)
    e_conf = CONF_RANK.get(extraction.get("confidence") if extraction else None, 0)

    if extraction and extraction["success"] and e_conf >= r_conf:
        return extraction["transcript_text"], "extractor", extraction["confidence"]
    if research.get("transcript_text"):
        return research["transcript_text"], research.get("source"), research.get("confidence")
    return None, None, None


class ManagerAgent:
    def __init__(self):
        self.anthropic_api_key = config.ANTHROPIC_API_KEY
        self.tavily_api_key    = config.TAVILY_API_KEY
        self.openai_api_key    = config.OPENAI_API_KEY
        self.researcher        = ResearcherAgent()
        self.extractor         = ExtractorAgent()
        self.cleaner           = CleanerAgent()
        self.transcriber       = TranscriberAgent()

    def run(self, input_data: dict) -> dict:
        print(f"Manager received: {input_data}")

        research = self.researcher.run(input_data)
        print(f"Researcher result: found={research['found']} confidence={research['confidence']}")

        extraction = None
        yt_url = _find_youtube_url(input_data, research)
        if yt_url:
            print(f"Running Extractor (YouTube captions) on {yt_url}")
            extraction = self.extractor.run(yt_url)
            print(f"Extractor result: success={extraction['success']} confidence={extraction['confidence']}")

        transcript_text, source, confidence = _pick_best(research, extraction)
        if source == "extractor" and yt_url:
            source = yt_url

        # Fallback: RSS feed → Transcriber (Whisper) when everything else fails
        from_transcriber = False
        if not transcript_text:
            # Prefer any non-YouTube audio URL the researcher already found
            raw_audio = research.get("audio_url") or ""
            audio_url = None if _YT_URL_RE.search(raw_audio) else (raw_audio or None)

            if not audio_url:
                show    = input_data.get("show", "")
                episode = input_data.get("episode", "")
                if show:
                    print("No transcript found — searching RSS for audio URL")
                    rss = find_audio_url(show, episode)
                    if rss["success"]:
                        audio_url = rss["audio_url"]
                        print(f"RSS found: '{rss['episode_title']}' → {audio_url}")
                    else:
                        print(f"RSS search failed: {rss['error']}")

            if audio_url:
                print(f"Running Transcriber on {audio_url}")
                transcription = self.transcriber.run(audio_url)
                if transcription["success"]:
                    transcript_text  = transcription["transcript_text"]
                    source           = audio_url
                    confidence       = transcription["confidence"]
                    from_transcriber = True
                    print(f"Transcriber succeeded, confidence={confidence}")
                else:
                    print(f"Transcriber failed: {transcription['error']}")

        # Cleaner: scrubbed boilerplate — not useful on clean Whisper output
        if transcript_text and confidence != "high" and not from_transcriber:
            show    = input_data.get("show", "")
            episode = input_data.get("episode", "")
            print(f"Confidence is '{confidence}' — running CleanerAgent")
            cleaned = self.cleaner.run(transcript_text, show=show, episode=episode)
            if cleaned["success"] and CONF_RANK.get(cleaned["confidence"], 0) >= CONF_RANK.get(confidence, 0):
                transcript_text = cleaned["transcript_text"]
                confidence      = cleaned["confidence"]
                print(f"Cleaner improved confidence to '{confidence}'")

        found = transcript_text is not None

        saved_path = None
        if found and CONF_RANK.get(confidence, 0) >= CONF_RANK["medium"]:
            filename   = _make_filename(input_data)
            saved_path = _save_transcript(filename, input_data, source, confidence, transcript_text)
            print(f"Transcript saved: {saved_path}")
        elif found:
            print(f"Transcript not saved — confidence too low ({confidence})")

        return {
            "status":          "found" if found else "not_found",
            "input":           input_data,
            "transcript_text": transcript_text,
            "source":          source,
            "confidence":      confidence,
            "saved_path":      saved_path,
            "research":        research,
            "extraction":      extraction,
        }
