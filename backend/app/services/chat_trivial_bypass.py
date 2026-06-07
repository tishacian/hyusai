"""Early local bypass for safe conversational trivial chat turns.

The detector is intentionally conservative. It only catches messages that are
clearly greetings, thanks, acknowledgements, or farewells, and it refuses to
fire as soon as the text looks like a question or a domain/document request.
"""
from __future__ import annotations

import re
import string
import unicodedata
from dataclasses import dataclass


_QUESTION_MARKERS_RE = re.compile(
    r"[?？]|\b(?:quel|quelle|quels|quelles|quoi|comment|pourquoi|ou|où|"
    r"where|what|which|how|why|when|who)\b",
    re.IGNORECASE,
)
_DOMAIN_CODE_RE = re.compile(
    r"\b[A-Z]{2,6}[\s_-]?\d{2,5}[A-Z]?\b|\b\d{3,}[A-Z]\b",
    re.IGNORECASE,
)
_DOMAIN_TERMS_RE = re.compile(
    r"\b("
    r"source|sources|document|documents|fichier|fichiers|file|files|"
    r"spl|manual|manuel|notice|procedure|proc[eé]dure|maintenance|"
    r"piece|pi[eè]ce|pieces|pi[eè]ces|part|parts|reference|r[eé]f[eé]rence|"
    r"machine|projet|project|injecteur|injector|cartouche|cartridge|"
    r"o[-\s]?ring|joint|filtering|filtration|vacuum|pompe|pump|"
    r"qdrant|retrieval|rag|golden|deep\s+search"
    r")\b",
    re.IGNORECASE,
)

_PUNCT_TABLE = str.maketrans({ch: " " for ch in string.punctuation})

_GREETING_PHRASES = {
    "bonjour",
    "bonsoir",
    "salut",
    "hello",
    "hi",
    "hey",
    "coucou",
}
_THANKS_PHRASES = {
    "merci",
    "merci beaucoup",
    "thanks",
    "thank you",
}
_ACK_PHRASES = {
    "ok",
    "okay",
    "d accord",
    "daccord",
    "dac",
    "ca marche",
    "cela marche",
    "parfait",
    "super",
    "bien recu",
    "recu",
    "entendu",
    "noted",
}
_FAREWELL_PHRASES = {
    "bye",
    "goodbye",
    "au revoir",
    "a plus",
    "a bientot",
}

_ALL_PHRASES = _GREETING_PHRASES | _THANKS_PHRASES | _ACK_PHRASES | _FAREWELL_PHRASES

_FILLER_TOKENS = {
    "a",
    "ah",
    "alors",
    "bien",
    "bon",
    "ca",
    "cela",
    "cest",
    "c",
    "est",
    "le",
    "la",
    "les",
    "oui",
    "non",
    "please",
    "stp",
    "svp",
    "tres",
    "tu",
    "vous",
}


@dataclass(frozen=True)
class TrivialBypass:
    content: str
    reason: str

    def metadata(self) -> dict[str, object]:
        return {
            "bypassed": True,
            "reason": self.reason,
            "trivial_bypass": True,
        }


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(no_accents.lower().translate(_PUNCT_TABLE).split())


def _reply_for(normalized: str) -> TrivialBypass:
    if not normalized:
        return TrivialBypass(
            content="Je suis la. Dites-moi ce que vous souhaitez faire.",
            reason="trivial_empty",
        )
    if normalized in _THANKS_PHRASES:
        return TrivialBypass(content="Avec plaisir.", reason="trivial_thanks")
    if normalized in _FAREWELL_PHRASES:
        return TrivialBypass(content="A bientot.", reason="trivial_farewell")
    if normalized in _ACK_PHRASES:
        return TrivialBypass(content="Bien recu.", reason="trivial_ack")
    return TrivialBypass(content="Bonjour, je vous ecoute.", reason="trivial_greeting")


def maybe_trivial_bypass(message: str) -> TrivialBypass | None:
    """Return a local reply for safe trivial messages, otherwise ``None``."""
    raw = str(message or "").strip()
    normalized = _fold(raw)
    if not normalized:
        return _reply_for(normalized)

    # Keep this very narrow: anything question-like or domain-like goes through
    # normal orchestration/retrieval.
    if len(raw) > 80:
        return None
    if _QUESTION_MARKERS_RE.search(raw):
        return None
    if _DOMAIN_CODE_RE.search(raw) or _DOMAIN_TERMS_RE.search(raw):
        return None

    if normalized in _ALL_PHRASES:
        return _reply_for(normalized)

    tokens = normalized.split()
    if not tokens or len(tokens) > 5:
        return None
    meaningful = [token for token in tokens if token not in _FILLER_TOKENS]
    if not meaningful:
        return None
    if all(token in _ALL_PHRASES for token in meaningful):
        return _reply_for(meaningful[-1])
    return None
