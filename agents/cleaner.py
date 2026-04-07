import anthropic
import config
from tools.transcript import validate_and_score

_MODEL = "claude-sonnet-4-6"
_MAX_INPUT_CHARS = 15_000


class CleanerAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def run(self, raw_text: str, show: str = "", episode: str = "") -> dict:
        """
        Use Claude to strip boilerplate and extract clean transcript text.
        Returns dict with: success, transcript_text, confidence, error.
        """
        context = f" ({show} — {episode})" if show and episode else ""
        prompt = (
            f"The following is raw text scraped from a podcast transcript page{context}.\n"
            "Extract only the spoken dialogue. Remove all navigation, ads, headers, "
            "footers, and boilerplate. Preserve speaker labels and timestamps exactly "
            "as they appear in the source.\n"
            "If there is no transcript content in the text, reply with exactly: NO_TRANSCRIPT\n\n"
            f"{raw_text[:_MAX_INPUT_CHARS]}"
        )

        try:
            message = self.client.messages.create(
                model=_MODEL,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            return {"success": False, "transcript_text": None, "error": str(e)}

        result = message.content[0].text.strip()
        if result == "NO_TRANSCRIPT" or len(result) < 200:
            return {"success": False, "transcript_text": None, "error": None}

        _, confidence = validate_and_score(result)
        return {"success": True, "transcript_text": result, "confidence": confidence, "error": None}
