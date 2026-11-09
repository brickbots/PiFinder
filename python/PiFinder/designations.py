"""
Designation parsing shared by the catalog import and the observing-list lookup.

One parser answers "which PiFinder listing does this designation name?" for
both, so a name an observing list resolves is the listing the import would
link it to. This module has no import-time dependencies beyond the standard
library, so the running app can use it.
"""

import re
from typing import Dict, Optional, Tuple

# Designation prefixes that name a PiFinder catalog, keyed on the lowercase,
# whitespace-free prefix as source catalogs write it. A prefix must be listed
# here for an alias to link one object to another; every other designation is
# kept as a plain name. The same catalog is spelled several ways across
# sources, and SIMBAD writes Abell planetaries as "PN A66 nn".
#
# Deliberately absent:
# - A bare "h". Herschel 400 uses catalog code "H", but "H 1-1" and similar
#   names are Haro planetary nebulae, and a bare "H 12" can also be Hubble.
# - A bare "a" or "b". Double-star sources use them for the discoverers
#   Aitken and van den Bos ("A 58", "B 53"). A loader whose source means
#   Abell or Barnard passes them as extra_aliases to parse_designation.
# - "wds" and "pk". Their designations end in digits that are not a sequence
#   ("WDS 00001+7508", "PK 120+09.1").
CATALOG_CODE_ALIASES: Dict[str, str] = {
    "abell": "Abl",
    "abl": "Abl",
    "pna66": "Abl",
    "arp": "Arp",
    "barnard": "B",
    "c": "C",
    "caldwell": "C",
    "col": "Col",
    "collinder": "Col",
    "cr": "Col",
    "egc": "EGC",
    "har": "Har",
    "herschel": "H",
    "ic": "IC",
    "lyn": "Lyn",
    "m": "M",
    "messier": "M",
    "ngc": "NGC",
    "rds": "RDS",
    "saa": "SaA",
    "sam": "SaM",
    "sar": "SaR",
    "sh2": "Sh2",
    "sharpless": "Sh2",
    "str": "Str",
    "ta2": "Ta2",
    "tlk": "TLK",
}

# A designation reads "<prefix><sequence>": the sequence is the trailing run of
# digits, the prefix is everything before it.
_DESIGNATION_RE = re.compile(r"(.*?)\s*(\d+)")

# The bare one-letter prefixes left out of CATALOG_CODE_ALIASES (see above).
# Each is a double-star discoverer in some sources and a PiFinder catalog in
# others, so "H 24", "h 99", "A 58" or "B 33" names no single object.
AMBIGUOUS_PREFIXES = frozenset({"a", "b", "h"})


def _prefix_and_sequence(raw: str) -> Optional[Tuple[str, int]]:
    """The lowercase, whitespace-free prefix and the sequence of ``raw``."""
    match = _DESIGNATION_RE.fullmatch(" ".join(raw.split()).lower())
    if match is None:
        return None
    prefix, sequence = match.groups()
    return prefix.rstrip("-.").replace(" ", ""), int(sequence)


def parse_designation(
    raw: str, extra_aliases: Optional[Dict[str, str]] = None
) -> Optional[Tuple[str, int]]:
    """Split a source designation into a PiFinder catalog code and sequence.

    "NGC 7008" -> ("NGC", 7008), "Sh 2-176" -> ("Sh2", 176),
    "PN A66 80" -> ("Abl", 80).

    Returns None when the designation names no PiFinder catalog. That covers
    the planetary-nebula families whose numeric part is compound: "M 1-92"
    (Minkowski), "H 3-29" (Haro), "K 2-1" (Kohoutek), "NGC 650-1" (the two
    halves of M76). Those leave a prefix of "m1", "h3", "k2" or "ngc650",
    none of which is a catalog, so they are rejected instead of being read as
    Messier 92, Herschel 29, "K 21" or NGC 6501.

    ``extra_aliases`` adds prefixes for one source, for example {"a": "Abl"}
    for a source that writes Abell planetaries as "A 50".
    """
    parsed = _prefix_and_sequence(raw)
    if parsed is None:
        return None
    key, sequence = parsed
    catalog_code = CATALOG_CODE_ALIASES.get(key)
    if catalog_code is None and extra_aliases:
        catalog_code = extra_aliases.get(key)
    if catalog_code is None:
        return None
    return catalog_code, sequence


def listing_named(name: str) -> Optional[Tuple[str, int]]:
    """The listing a name resolves to in the loaders' lookup, or None.

    parse_designation alone answers it, so its prefix allowlist governs every
    lookup: "B53" and "h99" name no listing, though Barnard 53 and Herschel
    400 #99 exist. ObjectFinder, the correction pass's checks
    (corrections.resolves_to) and the observing-list lookup all ask this, so
    they cannot disagree.
    """
    return parse_designation(name)


def is_ambiguous_designation(raw: str) -> bool:
    """True if ``raw`` is a designation with a bare "A", "B" or "H" prefix.

    "H 24" and "h 99" are double stars in SAC and WDS, and Herschel 400
    entries in PiFinder, so a name lookup must not answer them either.
    Compound designations such as "H 1-1" (Haro) are not ambiguous.
    """
    parsed = _prefix_and_sequence(raw)
    return parsed is not None and parsed[0] in AMBIGUOUS_PREFIXES


def designation(catalog_code: str, sequence: int) -> Optional[str]:
    """A designation of a listing that listing_named reads back, or None.

    ("Col", 399) -> "Col 399". The parser refuses a bare "H" or "B", so
    Herschel 400 and Barnard listings get their long form: ("H", 24) ->
    "Herschel 24", ("B", 33) -> "Barnard 33". A catalog with no readable
    prefix (WDS) gives None.
    """
    candidates = [catalog_code] + [
        prefix.capitalize()
        for prefix, code in CATALOG_CODE_ALIASES.items()
        if code == catalog_code
    ]
    for prefix in candidates:
        text = f"{prefix} {sequence}"
        if listing_named(text) == (catalog_code, sequence):
            return text
    return None
