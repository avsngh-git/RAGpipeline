"""Versioned scientific-text lexical analysis for BM25 retrieval."""

from __future__ import annotations

import re
import unicodedata

ANALYZER_ID = "scientific-en"
ANALYZER_REVISION = "v1"
NORMALIZATION_REVISION = "unicode-nfc-casefold-dashes-micro-v1"
TOKEN_PATTERN_REVISION = "scientific-compound-number-operator-v1"

_DASHES = str.maketrans(
    {
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2212": "-",  # minus sign
        "\u00b5": "\u03bc",  # micro sign to Greek small letter mu
    }
)
_ALNUM = r"[^\W_]+"
_TOKEN_PATTERN = re.compile(
    rf"(?P<number>(?<!\w)[+\-]?\d+(?:[.,]\d+)*(?:/\d+(?:[.,]\d+)*)?(?:[%‰])?(?!\w))"
    rf"|(?P<compound>{_ALNUM}(?:[-./+]{_ALNUM})+(?:\+{{2}}|#)?(?:[%‰])?)"
    rf"|(?P<word>{_ALNUM}(?:\+{{2}}|#)?(?:[%‰])?)"
    r"|(?P<operator><=|>=|!=|≤|≥|≈|±|×|÷|[@:;=<>+\-/^])",
    re.UNICODE,
)
_COMPONENT_SEPARATOR = re.compile(r"[-.,/+%‰#]")
_SYMBOLIC_COMPONENTS = {"+", "/"}


def tokenize_scientific_english(text: str) -> tuple[str, ...]:
    """Normalize and tokenize query/evidence text without dropping scientific terms.

    Source text is never modified. The analyzer applies Unicode NFC and casefolding,
    maps common Unicode dash/minus glyphs to ASCII hyphens and the micro sign to
    Greek mu, retains numeric and
    compound forms, emits compound components as aliases, and preserves comparison
    and arithmetic operators. It applies no stopword removal or stemming.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    normalized = unicodedata.normalize("NFC", text).casefold().translate(_DASHES)
    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(normalized):
        kind = match.lastgroup
        token = match.group()
        tokens.append(token)
        if kind not in {"number", "compound", "word"}:
            continue

        components = _COMPONENT_SEPARATOR.split(token)
        if len(components) == 1:
            continue
        for separator_match in _COMPONENT_SEPARATOR.finditer(token):
            separator = separator_match.group()
            if separator in _SYMBOLIC_COMPONENTS and not (
                separator == "+" and token.endswith("++")
            ):
                tokens.append(separator)
        tokens.extend(component for component in components if component)

    return tuple(tokens)
