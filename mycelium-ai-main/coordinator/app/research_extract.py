"""Source extraction, claims and contradictions (BIG #29).

Raw bytes -> labelled text -> passages -> claims with
evidence -> contradiction groups. Deterministic: same input,
same claims. No model involved in this layer.

Trust boundaries (enforced by construction):

- SYSTEM/DEVELOPER instructions: highest trust (this code).
- MYCELIUM INTERNAL data: controlled (budgets, allowlists).
- USER REQUEST: user-controlled (question text only).
- EXTERNAL SOURCE CONTENT: UNTRUSTED. Always wrapped and
  labelled; never executed, never followed, never written
  anywhere except the source record itself.
- MODEL OUTPUT: UNTRUSTED. Synthesis is interpretation.

Claim types: DIRECT_SOURCE_CLAIM (verbatim-adjacent passage),
INFERRED_CLAIM (deterministic triple parse), SYNTHESIZED_CLAIM
(model output only, never here), OPEN_QUESTION (gap the
sources leave). This module emits the first, second and
fourth; synthesis belongs to the engine's Ollama step.

Contradictions: deterministic triple grouping. Two claims
with the same normalized (subject, predicate) but different
normalized values form a contradiction group with
unresolved=true. Synthesis must report "A says X while B
says Y", never arbitrate truth.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

MAX_TEXT_CHARS = 20_000
MAX_PASSAGES = 40
MAX_PASSAGE_CHARS = 1_200
MAX_CLAIMS_PER_SOURCE = 12

CLAIM_TYPES = ("DIRECT_SOURCE_CLAIM", "INFERRED_CLAIM",
               "SYNTHESIZED_CLAIM", "OPEN_QUESTION")

#: Injection markers we label (not execute, not strip-blindly:
#: the text stays, the label warns).
INJECTION_PATTERNS = (
    "ignore previous instructions",
    "ignore all previous instructions",
    "disregard previous instructions",
    "execute the following",
    "run the following command",
    "approve this",
    "you are now",
    "new system prompt",
    "override your instructions",
)


class ExtractRefusedError(ValueError):
    """Extraction input refused; nothing parsed."""


@dataclass(frozen=True)
class Passage:
    """One citable text unit. Ordinal = evidence reference."""

    ordinal: int = 0
    text: str = ""
    section: str = ""


@dataclass(frozen=True)
class ExtractedClaim:
    """One deterministic claim candidate (no model)."""

    text: str = ""
    claim_type: str = "DIRECT_SOURCE_CLAIM"
    evidence_ordinal: int = 0
    evidence_text: str = ""
    subject: str = ""
    predicate: str = ""
    value: str = ""
    confidence: float = 0.5


@dataclass(frozen=True)
class ContradictionGroup:
    """Deterministic conflict: same subject+predicate,
    different values. Always unresolved=true here."""

    group_id: str = ""
    subject: str = ""
    predicate: str = ""
    claim_refs: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    detected_reason: str = ""
    unresolved: bool = True


class _TextExtractor(HTMLParser):
    """HTML -> text. Drops script/style/noscript, caps output."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip = 0
        self._title_parts: list[str] = []
        self._in_title = False
        self._chars = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4",
                   "tr", "div", "section", "article"):
            self._emit("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style", "noscript", "template") \
                and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag in ("p", "li", "h1", "h2", "h3", "h4", "tr",
                   "div", "section", "article"):
            self._emit("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self._title_parts.append(data)
            return
        self._emit(data)

    def _emit(self, text: str):
        if self._chars >= MAX_TEXT_CHARS:
            return
        room = MAX_TEXT_CHARS - self._chars
        chunk = text[:room]
        self._parts.append(chunk)
        self._chars += len(chunk)

    @property
    def text(self) -> str:
        raw = "".join(self._parts)
        lines = [re.sub(r"\s+", " ", line).strip()
                 for line in raw.split("\n")]
        return "\n".join(
            line for line in lines if line)[:MAX_TEXT_CHARS]

    @property
    def title(self) -> str:
        return re.sub(r"\s+", " ",
                      "".join(self._title_parts)).strip()[:300]


def html_to_text(html: str) -> tuple[str, str]:
    """Parse HTML to (title, clean text). Pure, bounded."""
    if not isinstance(html, str) or not html.strip():
        raise ExtractRefusedError("nothing to parse")
    parser = _TextExtractor()
    try:
        parser.feed(html[:MAX_TEXT_CHARS * 4])
        parser.close()
    except Exception as error:
        raise ExtractRefusedError(
            f"HTML unparsable: {type(error).__name__}")
    text = parser.text
    if not text.strip():
        raise ExtractRefusedError("no readable text found")
    return parser.title, text


def split_passages(text: str) -> list[Passage]:
    """Split clean text into bounded citable passages. Pure."""
    if not isinstance(text, str) or not text.strip():
        raise ExtractRefusedError("nothing to split")
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if current_len + len(line) > MAX_PASSAGE_CHARS \
                and current:
            chunks.append(" ".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append(" ".join(current))
    return [Passage(ordinal=index, text=chunk[:MAX_PASSAGE_CHARS])
            for index, chunk in enumerate(chunks[:MAX_PASSAGES])]


def injection_flags(text: str) -> list[str]:
    """Label prompt-injection markers in UNTRUSTED text. The
    text itself is never altered here; flags travel with it."""
    lowered = (text or "").lower()
    return [pattern for pattern in INJECTION_PATTERNS
            if pattern in lowered]


_TRIPLE = re.compile(
    r"^\s*(?P<subject>[A-ZÀ-Þ][^,.;:!?]{2,80}?)\s+"
    r"(?P<predicate>is|are|was|were|heeft|hebben|had|"
    r"bedraagt|bedragen|kost|kosten|bevat|bevatten|"
    r"weegt|wegen|meet|meten|duurt|duren|biedt|bieden)\s+"
    r"(?P<value>[^.;!?]{2,200})",
    re.IGNORECASE)


def _normalize_slot(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", " ",
                     (text or "").lower()).strip()
    return re.sub(r"\s+", " ", cleaned)[:120]


def extract_claims(passages: list[Passage], *,
                   keywords: list[str] = (),
                   max_claims: int = MAX_CLAIMS_PER_SOURCE
                   ) -> list[ExtractedClaim]:
    """Deterministic claim candidates from passages.

    Sentences matching a copula pattern become INFERRED_CLAIM
    triples; keyword-relevant sentences become
    DIRECT_SOURCE_CLAIMs. Every claim carries its passage
    ordinal as the exact evidence reference. No model, no
    invention: 0..N claims, uncited output impossible.
    """
    if not passages:
        return []
    keys = [key.lower() for key in (keywords or [])
            if isinstance(key, str) and key.strip()]
    claims: list[ExtractedClaim] = []
    seen: set[str] = set()
    for passage in passages:
        for sentence in re.split(r"(?<=[.!?])\s+", passage.text):
            sentence = sentence.strip()
            if len(sentence) < 25 or len(sentence) > 400:
                continue
            key = _normalize_slot(sentence)
            if key in seen:
                continue
            triple = _TRIPLE.match(sentence)
            relevant = (not keys or any(
                key in sentence.lower() for key in keys))
            if triple and relevant:
                seen.add(key)
                claims.append(ExtractedClaim(
                    text=sentence[:400],
                    claim_type="INFERRED_CLAIM",
                    evidence_ordinal=passage.ordinal,
                    evidence_text=passage.text[:400],
                    subject=_normalize_slot(
                        triple.group("subject")),
                    predicate=_normalize_slot(
                        triple.group("predicate")),
                    value=_normalize_slot(
                        triple.group("value")),
                    confidence=0.55))
            elif relevant and len(sentence) > 60 and len(
                    claims) < max(1, min(int(max_claims),
                                         MAX_CLAIMS_PER_SOURCE)):
                # Long keyword-relevant sentences carry direct
                # evidence even without a parseable triple.
                seen.add(key)
                claims.append(ExtractedClaim(
                    text=sentence[:400],
                    claim_type="DIRECT_SOURCE_CLAIM",
                    evidence_ordinal=passage.ordinal,
                    evidence_text=passage.text[:400],
                    confidence=0.5))
            if len(claims) >= max(1, min(int(max_claims),
                                         MAX_CLAIMS_PER_SOURCE)):
                break
        if len(claims) >= max(1, min(int(max_claims),
                                     MAX_CLAIMS_PER_SOURCE)):
            break
    return claims


def detect_contradictions(
        claims: list[tuple]) -> list[ContradictionGroup]:
    """Group (claim_id, subject, predicate, value, source_id)
    tuples into contradiction groups. Deterministic: same
    (subject, predicate), different values -> conflict.
    Pure function, no model arbitration."""
    buckets: dict[tuple, list] = {}
    for item in claims or []:
        claim_id, subject, predicate, value, source_id = item
        subject_n = _normalize_slot(subject)
        predicate_n = _normalize_slot(predicate)
        value_n = _normalize_slot(value)
        if not subject_n or not predicate_n or not value_n:
            continue
        buckets.setdefault((subject_n, predicate_n),
                           []).append((claim_id, value_n,
                                       source_id))
    groups: list[ContradictionGroup] = []
    index = 0
    for (subject, predicate), entries in sorted(buckets.items()):
        values = {value for _, value, _ in entries}
        if len(values) < 2:
            continue
        index += 1
        by_value: dict[str, list] = {}
        for claim_id, value, source_id in entries:
            by_value.setdefault(value, []).append(claim_id)
        groups.append(ContradictionGroup(
            group_id=f"cg_{index}",
            subject=subject, predicate=predicate,
            claim_refs=[claim_id for claim_id, _, _ in entries],
            sources=sorted({source for _, _, source in entries}),
            detected_reason=(
                f"same subject+predicate with {len(values)} "
                f"different values: "
                + "; ".join(sorted(values)[:4])[:300]),
            unresolved=True))
    return groups


def wrap_untrusted(text: str, *, source_id: str = "") -> str:
    """Wrap external text for model prompts. The model
    instruction (built by the engine) names this block
    UNTRUSTED DATA that must be summarized, never obeyed."""
    body = (text or "")[:4000]
    flags = injection_flags(body)
    banner = ("[UNTRUSTED EXTERNAL SOURCE"
              + (f" {source_id}" if source_id else "") + "]")
    if flags:
        banner += (" [INJECTION MARKERS FLAGGED: "
                   + ", ".join(flags[:4]) + "]")
    return f"{banner}\n{body}\n[END UNTRUSTED DATA]"
