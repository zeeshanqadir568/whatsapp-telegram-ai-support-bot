"""Deterministic checks around the LLM, so safety does not depend on the model obeying its prompt.

- ``sanitize_document_text`` drops instruction-like lines from documents before they are
  ingested (indirect prompt injection).
- ``check_reply`` blocks a generated reply that repeats the system prompt, asks for money,
  commits to a deal, or states an amount, day or time that is not in the retrieved context
  or the conversation.
"""

import re
from typing import Optional, Set, Tuple

_INJECTION_LINE = re.compile(
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|rules)"
    r"|disregard\s+(the|your|all|any)\s+(rules|instructions)"
    r"|\b(notice|instruction|instructions|message|note)\s+(to|for)\s+the\s+(assistant|ai|bot|model)\b"
    r"|\byou\s+are\s+now\b"
    r"|^\s*(system|assistant)\s*:"
    r"|\btell\s+(every|all|each)\s+(customer|user|visitor)s?\b",
    re.IGNORECASE,
)

_PAYMENT = re.compile(
    r"jazz\s*cash|easy\s*paisa|\biban\b|bank\s+(account|transfer)|account\s+(no|number)"
    r"|\btoken\s+(payment|money|amount)|advance\s+payment"
    r"|\b(send|transfer|deposit)\b[^.]{0,40}\b(rs\.?|pkr|rupees|money|payment|amount)\b",
    re.IGNORECASE,
)

_COMMITMENT = re.compile(
    r"\bdeal\s+(is\s+)?(done|confirmed|final|closed)\b|\b(i|we)\s+(agree|accept)\b"
    r"|\bprice\s+(is\s+)?(confirmed|locked|final)\b|\bguarantee",
    re.IGNORECASE,
)

_MONEY = re.compile(
    r"(?:rs\.?|pkr|\$)\s*(\d[\d,]*(?:\.\d+)?)\s*(thousand|lakh|lac|crore|k)?\b"
    r"|\b(\d[\d,]*(?:\.\d+)?)\s*(thousand|lakh|lac|crore)\b",
    re.IGNORECASE,
)
_MULTIPLIER = {"": 1, "k": 1e3, "thousand": 1e3, "lakh": 1e5, "lac": 1e5, "crore": 1e7}

_SCHEDULE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|every\s+day|daily|24/7"
    r"|24\s+hours|round\s+the\s+clock|\d{1,2}(?::\d{2})?\s?(?:am|pm))\b",
    re.IGNORECASE,
)

# Phrases that only appear in the system prompt; a reply containing one is leaking it
_PROMPT_LEAK = re.compile(
    r"knowledge\s+base\s+below|answer\s+only\s+with\s+facts|never\s+use\s+outside\s+knowledge"
    r"|</?knowledge_base>|</?user_message>|examples\s+of\s+correct\s+behaviou?r|data,\s+not\s+instructions",
    re.IGNORECASE,
)

_ROMAN_URDU = re.compile(r"\b(hai|hain|kya|kitna|kitne|kitni|aap|mein|nahi|kab|kahan|chahiye)\b", re.IGNORECASE)


def sanitize_document_text(text: str) -> Tuple[str, int]:
    """Remove lines that try to instruct the assistant. Returns (clean_text, lines_removed)."""
    kept, removed = [], 0
    for line in text.splitlines():
        if _INJECTION_LINE.search(line):
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept), removed


def _amounts(text: str) -> Set[float]:
    values = set()
    for m in _MONEY.finditer(text):
        number, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        values.add(round(float(number.replace(",", "")) * _MULTIPLIER[(unit or "").lower()], 2))
    return values


def _normalise(term: str) -> str:
    return re.sub(r"\s+", " ", term.lower().replace(":00", ""))


def check_reply(reply: str, allowed_text: str) -> Optional[str]:
    """Return why ``reply`` must be blocked, or None when it is safe to send.

    ``allowed_text`` is everything the reply may legitimately draw on: retrieved context,
    the user's message and the recent chat history.
    """
    if _PROMPT_LEAK.search(reply):
        return "repeats the system prompt"
    if _PAYMENT.search(reply):
        return "asks for payment"
    if _COMMITMENT.search(reply):
        return "commits to a deal or price"
    unknown_amounts = _amounts(reply) - _amounts(allowed_text)
    if unknown_amounts:
        return f"amount not in context: {sorted(unknown_amounts)}"
    allowed = _normalise(allowed_text)
    for m in _SCHEDULE.finditer(reply):
        if _normalise(m.group(0)) not in allowed:
            return f"schedule not in context: {m.group(0)}"
    return None


def safe_reply(user_message: str) -> str:
    """Fallback sent instead of a blocked reply, in the customer's language."""
    if _ROMAN_URDU.search(user_message):
        return "Is baare mein mere paas pakki maloomat nahi hai. Main aap ko hamari team se connect kar sakta hoon."
    return "I don't have confirmed information on that. I can connect you with our team to help."
