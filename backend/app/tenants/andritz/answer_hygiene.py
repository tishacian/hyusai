"""Answer hygiene for the Andritz workspace chat.

Andritz manuals end with public-facing boilerplate such as "contact Andritz
for more information". The users are Andritz experts, so the footer is noise
when a model copies it as the final next step. The shared chat agent asks this
family for an answer-tail filter; other families stream their answers
unbuffered and untouched.
"""

from __future__ import annotations

import re
import unicodedata

# The two prompt rules the shared chat agent takes from this family, verbatim.
SYSTEM_PROMPT_FOOTER_RULE = (
    'Do not reproduce generic supplier-document footers such as "contact Andritz for more information" '
    "as advice in the chat; Agentium users in the Andritz workspace are already Andritz experts."
)
ANSWER_SHAPING_FOOTER_RULE = (
    "- Do not end with generic document boilerplate asking the user to contact Andritz or an Andritz "
    "representative for more information, unless the user explicitly asked for contact details."
)


def _fold_for_policy(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()


CONTACT_QUERY_RE = re.compile(
    r"\b("
    r"contact|contacter|contactez|coordonn[ée]es|support|assistance|"
    r"repr[ée]sentant|email|e-mail|mail|t[ée]l[ée]phone|phone|qui\s+appeler"
    r")\b",
    re.IGNORECASE,
)

CONTACT_FOOTER_RE = re.compile(
    r"""
    (?:\s*(?:[-*]\s*)?)?
    (?:
        (?:
            (?:si\s+vous\s+(?:souhaitez|voulez|avez\s+besoin\s+de)[^\n.!?]{0,180})
            |(?:pour\s+(?:plus|toute|davantage)[^\n.!?]{0,180})
            |(?:for\s+(?:more|additional|further)[^\n.!?]{0,180})
            |(?:if\s+you\s+(?:need|want|would\s+like)[^\n.!?]{0,180})
        )
        (?:merci\s+de\s+|veuillez\s+|please\s+)?
        (?:contacter|contactez|contact|sollicitez|adressez-vous\s+a|reach\s+out\s+to)
        [^\n.!?]{0,240}\bandritz\b[^\n.!?]*
        |
        (?:merci\s+de\s+|veuillez\s+|please\s+)?
        (?:contacter|contactez|contact|sollicitez|adressez-vous\s+a|reach\s+out\s+to)
        [^\n.!?]{0,240}\bandritz\b[^\n.!?]{0,120}
        \b(?:information|informations|renseignement|renseignements|details|support|assistance|representant)\b
        [^\n.!?]*
    )
    (?:\s*\[\d{1,2}\])?
    [.!?]?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)

STREAM_TAIL_CHARS = 480


def query_requests_contact_info(query: str) -> bool:
    return bool(CONTACT_QUERY_RE.search(_fold_for_policy(query)))


def strip_contact_boilerplate(text: str, *, allow_contact_answer: bool = False) -> str:
    """Remove supplier-document contact footers from generated chat answers.

    Andritz manuals often contain public-facing closing boilerplate such as
    "contact Andritz for more information". In Agentium the users are already
    Andritz experts, so that footer is noise when copied as a final next step.
    We only strip it from the tail and keep explicit contact-answer turns.
    """

    if allow_contact_answer:
        return text
    stripped = (text or "").rstrip()
    if not stripped:
        return text or ""
    previous = None
    while stripped and stripped != previous:
        previous = stripped
        stripped = CONTACT_FOOTER_RE.sub("", stripped).rstrip()
    return stripped


class ContactBoilerplateStreamFilter:
    """Hold a small response tail so copied contact footers never flash in chat."""

    def __init__(self, *, enabled: bool = True, tail_chars: int = STREAM_TAIL_CHARS):
        self.enabled = enabled
        self.tail_chars = tail_chars
        self._tail = ""

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        if not self.enabled:
            return chunk
        self._tail += chunk
        if len(self._tail) <= self.tail_chars:
            return ""
        flush_to = len(self._tail) - self.tail_chars
        safe = self._tail[:flush_to]
        self._tail = self._tail[flush_to:]
        return safe

    def flush(self) -> str:
        if not self.enabled:
            tail = self._tail
            self._tail = ""
            return tail
        clean_tail = strip_contact_boilerplate(self._tail)
        self._tail = ""
        return clean_tail


def answer_tail_filter(query: str) -> ContactBoilerplateStreamFilter:
    """The stream filter the shared chat agent uses for this family."""

    return ContactBoilerplateStreamFilter(enabled=not query_requests_contact_info(query))
