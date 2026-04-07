import re
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled

from tools.transcript import validate_and_score

# Tags whose content is almost always boilerplate
_BOILERPLATE_TAGS = {
    "header", "footer", "nav", "aside", "form", "script", "style",
    "noscript", "iframe", "button", "svg", "figure", "figcaption",
}

_YT_ID_RE = re.compile(
    r'(?:youtube\.com/(?:watch\?.*v=|embed/|shorts/)|youtu\.be/)([\w-]{11})',
    re.IGNORECASE,
)


def _youtube_video_id(url: str) -> str | None:
    m = _YT_ID_RE.search(url)
    return m.group(1) if m else None


def _fetch_youtube_captions(video_id: str) -> tuple[str | None, str | None]:
    """Return (transcript_text, error)."""
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)
        text = " ".join(entry.text for entry in fetched)
        return text, None
    except TranscriptsDisabled:
        return None, "Transcripts are disabled for this video"
    except NoTranscriptFound:
        return None, "No transcript found for this video"
    except Exception as e:
        return None, str(e)


def _extract_page_text(url: str) -> tuple[str | None, str | None]:
    """Return (main_text, error) by scraping and stripping boilerplate."""
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
    except Exception as e:
        return None, str(e)

    soup = BeautifulSoup(resp.text, "html.parser")

    # Remove boilerplate tags in-place
    for tag in soup.find_all(_BOILERPLATE_TAGS):
        tag.decompose()

    # Prefer semantic content containers
    main = (
        soup.find("main")
        or soup.find("article")
        or soup.find(id=re.compile(r"content|main|body", re.I))
        or soup.find(class_=re.compile(r"content|main|body|post|entry", re.I))
        or soup.body
    )

    if not main:
        return None, "Could not locate main content element"

    lines = [line.strip() for line in main.get_text(separator="\n").splitlines()]
    # Drop truly empty lines but keep short lines (speaker names, timestamps, etc.)
    meaningful = [l for l in lines if len(l) > 2]
    text = "\n".join(meaningful)

    if not text:
        return None, "No meaningful text extracted from page"

    return text, None


class ExtractorAgent:
    def run(self, url: str) -> dict:
        video_id = _youtube_video_id(url)

        if video_id:
            text, error = _fetch_youtube_captions(video_id)
            # Auto-generated captions are inherently high-quality transcripts
            confidence = "high" if text else None
            return {
                "success":         text is not None,
                "transcript_text": text,
                "source_type":     "youtube_captions" if text else None,
                "confidence":      confidence,
                "error":           error,
            }
        else:
            # Refuse to scrape YouTube channel/playlist/user pages — no video ID means no captions
            # and YouTube channel pages only return boilerplate when scraped.
            if re.search(r'youtube\.com|youtu\.be', url, re.IGNORECASE):
                return {
                    "success":         False,
                    "transcript_text": None,
                    "source_type":     None,
                    "confidence":      None,
                    "error":           "YouTube URL has no video ID (channel/playlist page)",
                }
            text, error = _extract_page_text(url)
            if text:
                _, confidence = validate_and_score(text)
            else:
                confidence = None
            return {
                "success":         text is not None,
                "transcript_text": text,
                "source_type":     "page_text" if text else None,
                "confidence":      confidence,
                "error":           error,
            }
