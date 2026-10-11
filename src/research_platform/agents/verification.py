"""Deterministic checks that a drafted claim is grounded in its cited passage.

The generator returns each claim with a quote copied from the passage it cites. A
claim is kept only if the quote is really in that passage and the claim stays within
what the quote says. These checks replace the LLM support judge as the gate.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import astuple, dataclass

_STOPWORDS = frozenset(
    "a an the of in on at to for from by with and or but is are was were be been being "
    "this that these those it its as we our they their which who whom whose than then "
    "there here into over under can could may might will would should shall do does did "
    "has have had not no such also both each more most other some any all between using "
    "use used based via per".split()
)
# Words that strengthen a statement; a claim may use one only if its quote does.
_INTENSIFIERS = frozenset(
    "significantly substantially dramatically greatly consistently always never every "
    "only".split()
)
_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?!\w)")
_THOUSANDS_SUFFIX = re.compile(r"(\d+(?:\.\d+)?)k\b")
_HANDLE = re.compile(r"\bE[1-9][0-9]*\b")
_MIN_QUOTE_CHARS = 20
_MIN_OVERLAP = 0.5
_PROSE_QUOTE_SIMILARITY = 0.9


@dataclass(frozen=True)
class ClaimChecks:
    """Result of each grounding check for one claim."""

    quote_found: bool
    words_from_quote: bool
    numbers_from_quote: bool
    intensifiers_from_quote: bool
    no_handles_in_text: bool
    quote_names_its_row: bool
    no_other_row_named: bool

    @property
    def passed(self) -> bool:
        return all(astuple(self))


def verify_claim(text: str, quote: str, passage: str) -> ClaimChecks:
    """Check a claim and its quote against the passage the claim cites.

    - The quote occurs in the passage after normalization. Table quotes must match
      exactly; prose quotes may differ slightly (token similarity of at least 0.9),
      for example in hyphenation.
    - At least half of the claim's content words occur in the quote.
    - Every number and every intensifier in the claim occurs in the quote.
    - The claim text contains no evidence handle such as ``E7``.
    - For a labeled table row, the quote includes the row's label, and the claim
      names no other row of the table that the quote does not contain.
    """
    rows = _table_rows(passage)
    if rows:
        quote_found = _quote_in_passage(quote, passage)
    else:
        quote_found = _quote_in_passage(quote, passage) or _quote_similar(
            quote, passage
        )
    quote_names_its_row = True
    no_other_row_named = True
    if rows:
        quote_names_its_row, no_other_row_named = _row_checks(text, quote, rows)
    claim_words = normalize(text).split()
    quote_words = set(normalize(quote).split())
    return ClaimChecks(
        quote_found=quote_found,
        words_from_quote=content_overlap(text, quote) >= _MIN_OVERLAP,
        numbers_from_quote=_numbers(text) <= _numbers(quote),
        intensifiers_from_quote={w for w in claim_words if w in _INTENSIFIERS}
        <= quote_words,
        no_handles_in_text=_HANDLE.search(text) is None,
        quote_names_its_row=quote_names_its_row,
        no_other_row_named=no_other_row_named,
    )


def supported_by(text: str, source: str) -> bool:
    """Whether a sentence stays within a source: its words, numbers and intensifiers.

    These are the claim-side checks of ``verify_claim``; ``source`` is already verified
    text, so it is not looked up in a passage.
    """
    text_words = normalize(text).split()
    source_words = set(normalize(source).split())
    return (
        content_overlap(text, source) >= _MIN_OVERLAP
        and _numbers(text) <= _numbers(source)
        and {w for w in text_words if w in _INTENSIFIERS} <= source_words
        and _HANDLE.search(text) is None
    )


def normalize(text: str) -> str:
    """Lowercase, rejoin hyphenated line breaks and reduce punctuation to spaces.

    Periods are kept only inside numbers so that 0.253 and 0.254 stay distinct.
    """
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text.lower())
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s%.]", " ", text)).strip()


def content_overlap(text: str, quote: str) -> float:
    """Fraction of the claim's content words that occur in the quote."""
    words = content_words(text)
    if not words:
        return 0.0
    return len(words & content_words(quote)) / len(words)


def content_words(text: str) -> set[str]:
    """The text's normalized words, without stopwords and single characters."""
    return {
        word
        for word in normalize(text).split()
        if word not in _STOPWORDS and len(word) > 1
    }


def _quote_in_passage(quote: str, passage: str) -> bool:
    normalized = normalize(quote.strip().removeprefix("Row:"))
    return len(normalized) >= _MIN_QUOTE_CHARS and normalized in normalize(passage)


def _quote_similar(quote: str, passage: str) -> bool:
    """Whether some same-length window of the passage closely matches the quote."""
    quote_tokens = normalize(quote).split()
    passage_tokens = normalize(passage).split()
    if len(" ".join(quote_tokens)) < _MIN_QUOTE_CHARS or not passage_tokens:
        return False
    width = len(quote_tokens)
    for start in range(max(1, len(passage_tokens) - width + 1)):
        window = passage_tokens[start : start + width]
        matcher = difflib.SequenceMatcher(None, quote_tokens, window, autojunk=False)
        if matcher.ratio() >= _PROSE_QUOTE_SIMILARITY:
            return True
    return False


def _numbers(text: str) -> set[str]:
    expanded = _THOUSANDS_SUFFIX.sub(
        lambda match: f"{float(match.group(1)) * 1000:g}", text
    )
    return {number.replace(",", "") for number in _NUMBER.findall(expanded)}


def _table_rows(passage: str) -> list[tuple[str, str]]:
    """(label, body) for each labeled ``Row:`` line; the label is the first value."""
    rows: list[tuple[str, str]] = []
    for line in passage.splitlines():
        if not line.startswith("Row: "):
            continue
        body = line.removeprefix("Row: ")
        first = body.split(";", 1)[0]
        _, separator, value = first.partition(": ")
        rows.append(((value if separator else first).strip(), body))
    return rows


def _row_checks(
    text: str, quote: str, rows: list[tuple[str, str]]
) -> tuple[bool, bool]:
    normalized_quote = normalize(quote.strip().removeprefix("Row:"))
    source = next(
        (
            label
            for label, body in rows
            if normalized_quote[:40] and normalized_quote[:40] in normalize(body)
        ),
        None,
    )
    if source is None:
        return False, True
    own = normalize(source)
    names_its_row = bool(own) and own in normalized_quote
    normalized_text = normalize(text)
    for label, _ in rows:
        other = normalize(label)
        if (
            len(other) >= 4
            and other != own
            and other not in own
            and other in normalized_text
            and other not in normalized_quote
        ):
            return names_its_row, False
    return names_its_row, True
