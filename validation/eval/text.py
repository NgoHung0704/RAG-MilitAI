"""
Text normalization — an *independent* re-implementation of the catalogue's
``norm()`` (Reference Query Catalogue v0.3 §"Text normalization").

The generator owns its own ``normalize.py``; this module is deliberately a
separate copy so the eval runner cross-checks the matching logic rather than
inheriting it. The two must agree by specification, not by shared code.

norm(): NFKD-strip accents -> lowercase -> remove all dashes, whitespace, and
apostrophes. Fold-only and deterministic; no edit-distance / typo tolerance.

    André              -> andre
    Côtes-du-Nord      -> cotesdunord
    Saint-Jean / Saint Jean -> saintjean
    d'Aubigné          -> daubigne
"""

from __future__ import annotations

import unicodedata

# All apostrophe / dash variants the registers use.
_APOSTROPHES = "'’ʼ`´"
_DASHES = "-‐‑‒–—―−"
_STRIP = set(_APOSTROPHES) | set(_DASHES)


def norm(s) -> str:
    """Canonical fold used by every equality / CONTAINS in the oracle."""
    if s is None:
        return ""
    s = str(s)
    # NFKD then drop combining marks (accents).
    decomposed = unicodedata.normalize("NFKD", s)
    out = []
    for ch in decomposed:
        if unicodedata.combining(ch):
            continue
        if ch.isspace() or ch in _STRIP:
            continue
        out.append(ch.lower())
    return "".join(out)


def norm_eq(a, b) -> bool:
    return norm(a) == norm(b)


def norm_contains(haystack, needle) -> bool:
    return norm(needle) in norm(haystack)
