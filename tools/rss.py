"""RSS tool: find a podcast's feed and return an episode's audio URL."""
import re

import feedparser
import requests
from bs4 import BeautifulSoup
from tavily import TavilyClient

import config

_AUDIO_EXTS = re.compile(r'\.(mp3|m4a|ogg|wav|aac|opus|flac|mp4|m4b|webm)(?:\?|$)', re.IGNORECASE)
_FEED_URL_RE = re.compile(r'https?://\S+(?:feed|rss|\.xml)\S*', re.IGNORECASE)


def _looks_like_feed(url: str) -> bool:
    return bool(re.search(r'(?:feed|rss|\.xml)', url, re.IGNORECASE))


def _rss_link_from_html(html: str) -> str | None:
    """Extract RSS/Atom <link> tag from a page's <head>."""
    soup = BeautifulSoup(html, "html.parser")
    for mime in ("application/rss+xml", "application/atom+xml"):
        tag = soup.find("link", type=mime)
        if tag and tag.get("href"):
            return tag["href"]
    return None


def _audio_from_entry(entry: dict) -> str | None:
    for enc in entry.get("enclosures", []):
        href = enc.get("href", "")
        if enc.get("type", "").startswith("audio/") or _AUDIO_EXTS.search(href):
            return href
    for media in entry.get("media_content", []):
        href = media.get("url", "")
        if _AUDIO_EXTS.search(href):
            return href
    return None


def _try_feed(feed_url: str, episode: str = "") -> dict | None:
    """Parse feed_url and return the first matching audio entry, or None."""
    feed = feedparser.parse(feed_url)
    if not feed.entries:
        return None

    target = episode.lower().strip()
    entries = feed.entries

    if target:
        matched = [e for e in entries if target in e.get("title", "").lower()]
        if matched:
            entries = matched

    for entry in entries:
        audio = _audio_from_entry(entry)
        if audio:
            return {
                "success":       True,
                "audio_url":     audio,
                "episode_title": entry.get("title", ""),
                "feed_url":      feed_url,
                "error":         None,
            }
    return None


def _collect_candidates(results: list) -> tuple[list, list]:
    """Split Tavily results into feed URL candidates and page URL candidates."""
    feed_candidates = []
    page_candidates = []
    for r in results:
        url     = r.get("url", "")
        content = r.get("content", "")
        if _looks_like_feed(url):
            feed_candidates.append(url)
        else:
            page_candidates.append(url)
        for m in _FEED_URL_RE.findall(content):
            if m not in feed_candidates:
                feed_candidates.append(m)
    return feed_candidates, page_candidates


def _search_feeds(tavily: TavilyClient, query: str, episode: str) -> dict | None:
    """Run one Tavily query and try every feed/page candidate it returns."""
    _empty = {"success": False, "audio_url": None, "episode_title": None, "feed_url": None}
    try:
        results = tavily.search(query=query, max_results=5).get("results", [])
    except Exception:
        return None

    feed_candidates, page_candidates = _collect_candidates(results)

    for feed_url in feed_candidates:
        result = _try_feed(feed_url, episode)
        if result:
            return result

    for page_url in page_candidates[:3]:
        try:
            resp = requests.get(page_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            feed_url = _rss_link_from_html(resp.text)
            if feed_url:
                result = _try_feed(feed_url, episode)
                if result:
                    return result
        except Exception:
            continue

    return None


def find_audio_url(show: str, episode: str = "") -> dict:
    """
    Search for a podcast RSS feed and return the audio URL for the most recent
    (or title-matching) episode. Tries multiple Tavily queries before giving up.

    Returns: {success, audio_url, episode_title, feed_url, error}
    """
    _empty = {"success": False, "audio_url": None, "episode_title": None, "feed_url": None}
    tavily = TavilyClient(api_key=config.TAVILY_API_KEY)

    ep_hint = f' "{episode}"' if episode else ""
    queries = [
        f'"{show}" podcast RSS feed',
        f'"{show}"{ep_hint} podcast omny OR spreaker OR podbean OR anchor feed',
        f'"{show}"{ep_hint} podcast audio mp3',
    ]

    for query in queries:
        result = _search_feeds(tavily, query, episode)
        if result:
            return result

    return {**_empty, "error": f"Could not find RSS feed or audio for '{show}'"}
