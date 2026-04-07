import re
import requests
from bs4 import BeautifulSoup
from tavily import TavilyClient

import config
from tools.transcript import validate_and_score

# Audio file extensions considered a findable audio URL
_AUDIO_EXTS = re.compile(r'\.(mp3|m4a|ogg|wav|aac|opus|flac)(\?|$)', re.IGNORECASE)

# Patterns that suggest a block of text is an actual transcript (English + Hebrew)
_TRANSCRIPT_SIGNALS = re.compile(
    r'\b(transcript|full transcript|show notes.*transcript|episode transcript)\b|תמלול|תמליל',
    re.IGNORECASE,
)

_HEBREW_RE = re.compile(r'[\u0590-\u05FF\uFB1D-\uFB4F]')


def _fetch_html(url: str) -> str | None:
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _extract_from_html(html: str) -> dict:
    """Return transcript_text and/or audio_url found in raw HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # --- audio URL ---
    audio_url = None
    for tag in soup.find_all(["audio", "source"]):
        src = tag.get("src", "")
        if _AUDIO_EXTS.search(src):
            audio_url = src
            break
    if not audio_url:
        for tag in soup.find_all(True):
            for attr in ("href", "src", "data-url", "data-src"):
                val = tag.get(attr, "")
                if _AUDIO_EXTS.search(val):
                    audio_url = val
                    break
            if audio_url:
                break

    # --- transcript text ---
    transcript_text = None
    for tag in soup.find_all(True, {"id": _TRANSCRIPT_SIGNALS, "class": _TRANSCRIPT_SIGNALS}):
        text = tag.get_text(separator="\n", strip=True)
        if len(text) > 200:
            transcript_text = text
            break

    if not transcript_text:
        for tag in soup.find_all(["div", "section", "article"]):
            text = tag.get_text(separator="\n", strip=True)
            if _TRANSCRIPT_SIGNALS.search(text) and len(text) > 500:
                transcript_text = text
                break

    return {"transcript_text": transcript_text, "audio_url": audio_url}


def _accept(text: str) -> tuple[bool, str]:
    """Validate transcript quality. Returns (accepted, confidence)."""
    valid, confidence = validate_and_score(text)
    return valid, confidence


class ResearcherAgent:
    def __init__(self):
        self.tavily = TavilyClient(api_key=config.TAVILY_API_KEY)

    def run(self, input_data: dict) -> dict:
        mode = input_data.get("mode")
        tried = []
        transcript_text = None
        audio_url = None
        source = None
        confidence = None

        if mode == "url":
            label = input_data.get("url", "")
        else:
            show = input_data.get("show", "")
            episode = input_data.get("episode", "")
            label = f"{show} {episode}".strip()

        is_hebrew          = bool(_HEBREW_RE.search(label))
        transcript_keyword = "תמלול" if is_hebrew else "transcript"

        # ------------------------------------------------------------------ #
        # Step 1 (url mode only): fetch the episode page and scrape it        #
        # ------------------------------------------------------------------ #
        if mode == "url":
            url = input_data["url"]
            tried.append(f"fetch:{url}")
            html = _fetch_html(url)
            if html:
                extracted = _extract_from_html(html)
                audio_url = extracted["audio_url"]
                candidate = extracted["transcript_text"]
                if candidate:
                    valid, conf = _accept(candidate)
                    if valid:
                        transcript_text = candidate
                        source = url
                        confidence = conf
                    else:
                        tried.append(f"rejected:fetch:{url} (failed quality check)")
                if audio_url and not source:
                    source = url

        # ------------------------------------------------------------------ #
        # Step 2: web search for a transcript                                 #
        # ------------------------------------------------------------------ #
        if not transcript_text:
            query = f"{label} {transcript_keyword}"
            tried.append(f"tavily:{query}")
            try:
                results = self.tavily.search(query=query, max_results=5)
                for r in results.get("results", []):
                    page_html = _fetch_html(r["url"])
                    if page_html:
                        extracted = _extract_from_html(page_html)
                        if extracted["transcript_text"]:
                            valid, conf = _accept(extracted["transcript_text"])
                            if valid:
                                transcript_text = extracted["transcript_text"]
                                source = r["url"]
                                confidence = conf
                                break
                            else:
                                tried.append(f"rejected:{r['url']} (failed quality check)")
                    # Tavily content snippet fallback
                    if not transcript_text:
                        snippet = r.get("content", "")
                        if len(snippet) > 300:
                            valid, conf = _accept(snippet)
                            if valid:
                                transcript_text = snippet
                                source = r["url"]
                                confidence = conf
                                break
                            else:
                                tried.append(f"rejected:snippet:{r['url']} (failed quality check)")
            except Exception as e:
                tried.append(f"tavily error: {e}")

        # ------------------------------------------------------------------ #
        # Step 3: YouTube search                                              #
        # ------------------------------------------------------------------ #
        if not transcript_text and not audio_url:
            query = f"{label} site:youtube.com"
            # For Hebrew content, also search without site restriction if needed
            tried.append(f"tavily:{query}")
            try:
                results = self.tavily.search(query=query, max_results=3)
                for r in results.get("results", []):
                    if "youtube.com" in r.get("url", ""):
                        audio_url = r["url"]
                        source = r["url"]
                        break
            except Exception as e:
                tried.append(f"tavily error: {e}")

        found = bool(transcript_text or audio_url)
        return {
            "found":           found,
            "transcript_text": transcript_text,
            "audio_url":       audio_url,
            "source":          source,
            "confidence":      confidence,
            "tried":           tried,
        }
