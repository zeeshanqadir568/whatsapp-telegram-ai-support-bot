"""Deterministic checks around the LLM, so safety does not depend on the model obeying its prompt.

- ``sanitize_document_text`` drops instruction-like lines from documents before they are
  ingested (indirect prompt injection).
- ``is_override_request`` spots customer messages that try to script the reply ("reply only
  with ...", "you are now ..."), so they are refused before the LLM sees them.
- ``check_reply`` blocks a generated reply that repeats the system prompt, asks for money or
  card / bank details, commits to a deal, or states an amount, percentage, day or time that
  is not in the retrieved context. A customer's own day or amount may only be echoed back
  as an acknowledgement ("Noted Monday"), never as a business claim ("We are open Monday").
- ``scrub_internal_terms`` rewrites internal wording ("the KNOWLEDGE BASE") for customers.
"""

import re
from typing import List, Optional, Set, Tuple

_INJECTION_LINE = re.compile(
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions|rules)"
    r"|disregard\s+(the|your|all|any)\s+(rules|instructions)"
    r"|\b(notice|instruction|instructions|message|note)\s+(to|for)\s+the\s+(assistant|ai|bot|model)\b"
    r"|\byou\s+are\s+now\b"
    r"|^\s*(system|assistant)\s*:"
    r"|\btell\s+(every|all|each)\s+(customer|user|visitor)s?\b"
    # A line addressed to the bot: "AI, from now on ...", "Assistant, please ..."
    r"|^\W*(hey\s+|dear\s+)?(the\s+)?(ai|assistant|bot|chat\s*bot|gpt|claude)\s*[,:]"
    r"|\b(you|the\s+(assistant|bot|ai|model))\s+(must|should|shall|will)\s+(now\s+|always\s+)?"
    r"(tell|say|offer|reply|respond)\b"
    # Telling the bot to ask customers for card / bank secrets
    r"|\bask\b[^.]{0,40}\b(customer|user|visitor|client|patient|caller)s?\b[^.]{0,30}"
    r"\b(card|cvv|cvc|pin|otp|password|bank|iban)\b",
    re.IGNORECASE,
)

# Customer messages that try to script the bot's reply or replace its role
_OVERRIDE = re.compile(
    r"\b(reply|respond|answer|say|write|print|output|type)\b[^.\n]{0,15}\bonly\s+(with|this|these|the\s+words?)\b"
    r"|\b(only|just)\s+(reply|respond|answer|say|write|print|output)\s+(with|this|:)"
    r"|\b(reply|respond|answer|say|write|print|output)\s+(with\s+)?(exactly|verbatim|word\s+for\s+word)\s*(:|this\b|the\s+following\b|[\"'])"
    r"|\breply\s+with\s+the\s+word\b|\brepeat\s+(after\s+me|this|the\s+following)\b"
    r"|\byou\s+are\s+now\b|\bfrom\s+now\s+on\s+you\b|\bpretend\s+(to\s+be|you\s+are)\b"
    r"|\b(developer|god|dan|jailbreak)\s+mode\b"
    r"|ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier|your)\s+(instructions|rules|prompt)"
    r"|</?\s*(system|user_message|knowledge_base)\s*>"
    # Roman Urdu: "hidayat bhool jao", "ab tum ek pirate ho", "sirf 'ARRR' likho"
    r"|\bhidayat\b[^.\n]{0,20}\bbhool|\bab\s+(tum|aap)\s+ek\s+\w+\s+(ho|hain)\b"
    r"|\bsirf\b[^.\n]{0,30}\b(likho|likhen|likhein|bolo|kaho)\b",
    re.IGNORECASE,
)

_PAYMENT = re.compile(
    r"jazz\s*cash|easy\s*paisa|\biban\b|bank\s+(account|transfer)|account\s+(no|number)"
    r"|\btoken\s+(payment|money|amount)|advance\s+payment"
    r"|\b(send|transfer|deposit)\b[^.]{0,40}\b(rs\.?|pkr|rupees|money|payment|amount)\b",
    re.IGNORECASE,
)

# Card or bank secrets; a support bot never asks for these
_CARD = re.compile(
    r"\b(credit|debit|bank|atm)\s*card\b|\bcard\s*(number|no\.?|details|info)\b|\bcvv\b|\bcvc\b"
    r"|\bexpiry\s+date\b|\bbank\s+(details|info|information)\b|\botp\b|\bpin\s*(code|number)\b",
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

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)", re.IGNORECASE)

_SCHEDULE = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|every\s+day|daily|24/7"
    r"|24\s+hours|round\s+the\s+clock|\d{1,2}(?::\d{2})?\s?(?:am|pm))\b",
    re.IGNORECASE,
)
# Schedule terms that describe the business, never a customer's booking
_BUSINESS_ONLY_SCHEDULE = re.compile(r"24|every|daily|round", re.IGNORECASE)

# A sentence that echoes the customer's own request back ...
_ECHO = re.compile(
    r"\b(noted|note|your|you(?:'ve|\s+have)?\s+(mentioned|said|asked|requested|chose|want|prefer)"
    r"|preferred|requested|budget)\b",
    re.IGNORECASE,
)
# ... and makes no claim about the business
_CLAIM = re.compile(
    r"\b(open|opens|closed?|hours|timings?|walk[\s-]?in|available|cost|costs|price[ds]?|fees?"
    r"|charges?|rent|free|discount|off|now|only|offer|special|deal|pay|payment)\b",
    re.IGNORECASE,
)

# Phrases that only appear in the system prompt; a reply containing one is leaking it
_PROMPT_LEAK = re.compile(
    r"knowledge\s+base\s+below|answer\s+only\s+with\s+facts|never\s+use\s+outside\s+knowledge"
    r"|</?knowledge_base>|</?user_message>|examples\s+of\s+correct\s+behaviou?r|data,\s+not\s+instructions",
    re.IGNORECASE,
)

# Internal wording that customers should not see ("The KNOWLEDGE BASE does not mention ...")
_INTERNAL_TERM = re.compile(r"(?:\b(?:the|our|my|this)\s+)?\bknowledge[\s_-]*base\b", re.IGNORECASE)
_RECORDS_VERB = re.compile(r"\b([Oo]ur records) (does not|doesn't|has|is)\b")
_PLURAL_VERB = {"does not": "do not", "doesn't": "don't", "has": "have", "is": "are"}

_ROMAN_URDU = re.compile(r"\b(hai|hain|kya|kitna|kitne|kitni|aap|mein|nahi|kab|kahan|chahiye)\b", re.IGNORECASE)
_ROMAN_URDU_COMMAND = re.compile(r"\b(tum|sirf|likho|bolo|jao|hidayat)\b", re.IGNORECASE)


def sanitize_document_text(text: str) -> Tuple[str, int]:
    """Remove lines that try to instruct the assistant. Returns (clean_text, lines_removed)."""
    kept, removed = [], 0
    for line in text.splitlines():
        if _INJECTION_LINE.search(line):
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept), removed


def is_override_request(message: str) -> bool:
    """True when a customer message tries to script the reply or swap the bot's role."""
    return bool(_OVERRIDE.search(message))


def _amounts(text: str) -> Set[float]:
    values = set()
    for m in _MONEY.finditer(text):
        number, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        values.add(round(float(number.replace(",", "")) * _MULTIPLIER[(unit or "").lower()], 2))
    return values


def _percents(text: str) -> Set[float]:
    return {float(m.group(1)) for m in _PERCENT.finditer(text)}


def _normalise(term: str) -> str:
    return re.sub(r"\s+", " ", term.lower().replace(":00", ""))


def _sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def check_reply(reply: str, context: str, conversation: str = "") -> Optional[str]:
    """Return why ``reply`` must be blocked, or None when it is safe to send.

    ``context`` is the retrieved knowledge base text: the only source for business facts
    (prices, percentages, opening days and hours). ``conversation`` is the customer's
    message plus recent history. A visitor controls it, so its amounts, days and times are
    accepted only in a sentence that acknowledges the customer's request and makes no
    claim about the business.
    """
    if _PROMPT_LEAK.search(reply):
        return "repeats the system prompt"
    if _CARD.search(reply):
        return "asks for card or bank details"
    if _PAYMENT.search(reply):
        return "asks for payment"
    if _COMMITMENT.search(reply):
        return "commits to a deal or price"
    unknown_percents = _percents(reply) - _percents(context)
    if unknown_percents:
        return f"percentage not in context: {sorted(unknown_percents)}"

    context_amounts, user_amounts = _amounts(context), _amounts(conversation)
    allowed, user_said = _normalise(context), _normalise(conversation)
    for sentence in _sentences(reply):
        echo = bool(_ECHO.search(sentence)) and not _CLAIM.search(sentence)
        for amount in _amounts(sentence) - context_amounts:
            if not (echo and amount in user_amounts):
                return f"amount not in context: {amount}"
        for m in _SCHEDULE.finditer(sentence):
            term = _normalise(m.group(0))
            if term in allowed:
                continue
            if not (echo and term in user_said and not _BUSINESS_ONLY_SCHEDULE.search(term)):
                return f"schedule not in context: {m.group(0)}"
    return None


def scrub_internal_terms(reply: str) -> str:
    """Replace internal wording such as "The KNOWLEDGE BASE does not mention ..."."""

    def repl(m: re.Match) -> str:
        before = reply[: m.start()].rstrip()
        return "Our records" if not before or before[-1] in ".!?:\n" else "our records"

    text = _INTERNAL_TERM.sub(repl, reply)
    return _RECORDS_VERB.sub(lambda m: f"{m.group(1)} {_PLURAL_VERB[m.group(2)]}", text)


def refusal_reply(user_message: str) -> str:
    """Sent instead of calling the LLM when a message tries to script the reply."""
    if _ROMAN_URDU.search(user_message) or _ROMAN_URDU_COMMAND.search(user_message):
        return "Main sirf hamare business ke baare mein sawalon mein madad kar sakta hoon. Aap kya poochna chahte hain?"
    return "I can only help with questions about our business. What would you like to know?"


def safe_reply(user_message: str) -> str:
    """Fallback sent instead of a blocked reply, in the customer's language."""
    if _ROMAN_URDU.search(user_message):
        return "Is baare mein mere paas pakki maloomat nahi hai. Main aap ko hamari team se connect kar sakta hoon."
    return "I don't have confirmed information on that. I can connect you with our team to help."
