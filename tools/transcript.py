"""Shared transcript validation and confidence scoring."""
import re
from collections import Counter

_TIMESTAMP_RE = re.compile(r'\[\d{2}:\d{2}(:\d{2})?\]|\(\d{2}:\d{2}(:\d{2})?\)')
# Matches "Name:" (colon style) OR "Name\n(HH:MM:SS)" (Lex Fridman style)
# Uses literal space (not \s) so newlines are never consumed inside the name.
_SPEAKER_RE   = re.compile(
    r'^[A-Z][A-Za-z .\-]{1,30}(?::\s|\n\(\d{2}:\d{2}(?::\d{2})?\))',
    re.MULTILINE,
)
_FILLER_RE    = re.compile(r'\b(um+|uh+|you know|I mean|right\?|yeah|so I|and I)\b', re.IGNORECASE)
_METADATA_RE  = re.compile(
    r'\d{4,}\s*(subscribers|likes|views|comments)|'
    r'(follow|subscribe|listen\s+on)\s+\w.*?https?://',
    re.IGNORECASE,
)
_SOCIAL_URL_RE = re.compile(r'https?://\S+', re.IGNORECASE)


def validate_and_score(text: str) -> tuple[bool, str]:
    """
    Returns (is_valid, confidence) where confidence is 'high', 'medium', or 'low'.
    is_valid is False when the text is clearly not a transcript.
    """
    if not text:
        return False, "low"

    words = text.split()
    word_count = len(words)

    # Hard requirement: at least 500 words
    if word_count < 500:
        return False, "low"

    # Reject if heavily metadata/social-media flavoured
    metadata_hits = len(_METADATA_RE.findall(text))
    url_hits = len(_SOCIAL_URL_RE.findall(text))
    if metadata_hits >= 2 or url_hits > 10:
        return False, "low"

    # Reject if it looks like a song (many repeated non-trivial lines)
    lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 10]
    if lines:
        repeated = sum(1 for c in Counter(lines).values() if c >= 3)
        if repeated >= 3:
            return False, "low"

    # Positive speech signals
    has_timestamps = bool(_TIMESTAMP_RE.search(text))
    speaker_hits   = len(_SPEAKER_RE.findall(text))
    has_speakers   = speaker_hits >= 3
    filler_hits    = len(_FILLER_RE.findall(text))
    has_fillers    = filler_hits >= 5

    if has_timestamps and has_speakers:
        return True, "high"
    if has_timestamps or has_speakers or has_fillers:
        return True, "medium"

    # Passes word count but no strong speech signals — could still be transcript
    return True, "medium"


# Numeric rank for comparison
CONF_RANK: dict[str | None, int] = {"high": 3, "medium": 2, "low": 1, None: 0}
