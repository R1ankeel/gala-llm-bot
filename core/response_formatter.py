import re

FALLBACK_REPLY = "…"

_WRAP = r"""[«»"'“”‘’*]"""


def _strip_leading_nick(text: str, nick: str) -> str:
    pattern = re.compile(
        rf"^\s*{_WRAP}*{re.escape(nick)}{_WRAP}*\s*[,:—:]\s*{_WRAP}*\s*",
        re.IGNORECASE,
    )
    return pattern.sub("", text)


def format_reply(raw_llm_output: str, addressee_nick: str) -> str:
    """Чистит сырой ответ модели и приклеивает ровно один ник в начале."""
    text = (raw_llm_output or "").strip()

    while True:
        stripped = _strip_leading_nick(text, addressee_nick)
        if stripped == text:
            break
        text = stripped
    text = text.strip().lstrip(",.")

    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}", "\n", text)

    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'«»“”":
        text = text[1:-1].strip()

    if not text:
        return f"{addressee_nick}, {FALLBACK_REPLY}"
    return f"{addressee_nick}, {text}"
