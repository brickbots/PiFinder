"""
Tests for the Steinicke NGC/IC object-type parsing.

These exercise ``preprocess_steinicke_type`` (and its helpers) directly --
the function where catalog object types are derived during import. The
data-validation tests in ``test_catalog_data.py`` only spot-check a handful
of well-known objects in the *built* database, which is why a whole class of
globular clusters mis-typed as galaxies (NGC 7006, M 75, ...) slipped through.

Two layers of coverage:

* Tier 1 -- pure unit tests of the mapping function, one case per decision
  branch and known ambiguity. No database required.
* Tier 2 -- an audit over the real Steinicke source: every object that the
  globular rescue is *eligible* to reclassify (a globular cross-ID plus a
  concentration-class TYPE) must end up typed ``Gb``. This catches the whole
  class generically rather than enumerating named objects.
"""

import json

import pytest

import PiFinder.utils as utils
from PiFinder.catalog_imports.steinicke_loader import (
    is_galaxy_type,
    is_trumpler_class,
    preprocess_steinicke_type,
)


# ---------------------------------------------------------------------------
# Tier 1: pure-function mapping cases
# ---------------------------------------------------------------------------

# (steinicke_type, remarks, expected_pifinder_type, label)
MAPPING_CASES = [
    # The bug class: a bare Roman numeral is an Irregular galaxy, but the same
    # numeral with a GCL/globular cross-ID is a globular's concentration class.
    ("I", [], "Gx", "bare-I-is-irregular-galaxy"),
    ("I", ["GCL 119"], "Gb", "I+GCL-is-globular-ngc7006"),
    ("I", ["M 75", "GCL 116"], "Gb", "I+GCL-is-globular-m75"),
    ("IV", ["GCL 1"], "Gb", "IV+GCL-is-globular"),
    ("XII", ["globular"], "Gb", "XII+globular-keyword"),
    # Trumpler open-cluster classes (no globular signal) stay open clusters.
    ("II", [], "OC", "roman-numeral-trumpler-oc"),
    ("II1p", [], "OC", "trumpler-class-oc"),
    ("III2m", [], "OC", "trumpler-class-oc-2"),
    # An object that merely *mentions* a globular but is not one (IC 4802 is a
    # star group inside Pal 9). Its exact-match type wins; it must stay Ast.
    ("*Grp", ["in GCL N 6717=Pal 9"], "Ast", "stargroup-in-globular-ic4802"),
    # Exact-match table entries.
    ("GCL", [], "Gb", "explicit-globular"),
    ("OCL", [], "OC", "explicit-open-cluster"),
    ("PN", [], "PN", "planetary-nebula"),
    ("SNR", [], "Nb", "supernova-remnant-as-nebula"),
    ("DN", [], "DN", "dark-nebula"),
    ("Nova", [], "*", "nova-as-star"),
    ("*2", [], "D*", "double-star"),
    ("**", [], "D*", "double-star-alt"),
    ("NF", [], "?", "not-found-unknown"),
    # Combination types.
    ("OCL+EN", [], "C+N", "cluster-plus-nebula"),
    ("EN+RN", [], "Nb", "emission-plus-reflection-nebula"),
    ("RN+*", [], "C+N", "reflection-nebula-plus-star"),
    # Galaxy Hubble-type patterns.
    ("E", [], "Gx", "elliptical-galaxy"),
    ("Sb", [], "Gx", "spiral-galaxy"),
    ("SBc", [], "Gx", "barred-spiral-galaxy"),
    ("S0", [], "Gx", "lenticular-galaxy"),
    # Suffix stripping recurses back into the mapper.
    ("Sb?", [], "Gx", "galaxy-with-uncertainty-suffix"),
    ("Sa pec", [], "Gx", "peculiar-galaxy"),
    # Empty / missing type.
    ("", [], "?", "empty-type"),
]


@pytest.mark.unit
@pytest.mark.parametrize(
    "steinicke_type, remarks, expected",
    [(c[0], c[1], c[2]) for c in MAPPING_CASES],
    ids=[c[3] for c in MAPPING_CASES],
)
def test_preprocess_steinicke_type(steinicke_type, remarks, expected):
    assert preprocess_steinicke_type(steinicke_type, remarks) == expected


@pytest.mark.unit
def test_roman_numeral_galaxy_globular_overlap():
    """
    Document the ambiguity at the root of the bug: ``is_galaxy_type`` and
    ``is_trumpler_class`` both accept the bare numeral "I", so ordering in
    ``preprocess_steinicke_type`` (globular rescue before the galaxy check)
    is what disambiguates -- not the helpers themselves.
    """
    assert is_galaxy_type("I") is True
    assert is_trumpler_class("I") is True
    # The remarks are the tie-breaker.
    assert preprocess_steinicke_type("I", []) == "Gx"
    assert preprocess_steinicke_type("I", ["GCL 1"]) == "Gb"


@pytest.mark.unit
def test_remarks_accepts_string_and_list():
    """Remarks arrive as a list (ID1-ID11) but a bare string must also work."""
    assert preprocess_steinicke_type("I", "GCL 119") == "Gb"
    assert preprocess_steinicke_type("I", ["GCL 119"]) == "Gb"


# ---------------------------------------------------------------------------
# Tier 2: invariant audit over the real Steinicke source
# ---------------------------------------------------------------------------

# Globulars whose Steinicke TYPE is a concentration class ("I") and which were
# historically mis-typed as galaxies. Used to prove the audit actually inspects
# real data rather than silently examining an empty set.
KNOWN_CONCENTRATION_CLASS_GLOBULARS = {
    ("N", 2808),
    ("N", 5824),
    ("N", 5834),
    ("N", 6864),
    ("N", 7006),
}


def _load_steinicke_source():
    """
    Load the parsed Steinicke catalog, generating it from the committed source
    ZIP if the JSON has not been produced yet (it is gitignored).
    """
    json_path = utils.astro_data_dir / "ngc_ic_m/steinicke/steinicke_catalog.json"
    if not json_path.exists():
        from PiFinder.catalog_imports.steinicke_loader import _extract_and_process_data

        _extract_and_process_data()
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.unit
def test_globular_crossid_never_typed_as_galaxy():
    """
    Class-level invariant: any Steinicke object carrying a globular cross-ID
    (GCL.../globular in its remarks) together with a concentration-class TYPE
    must map to ``Gb``, never to a galaxy. This would have caught NGC 7006 and
    the four other globulars without anyone naming them.
    """
    data = _load_steinicke_source()

    examined = set()
    offenders = []
    for obj in data:
        prefix = obj.get("catalogue_prefix")
        number = obj.get("catalogue_number")
        if prefix not in ("N", "I") or not number:
            continue
        remarks = obj.get("remarks") or []
        remarks_str = " ".join(str(r) for r in remarks if r)
        has_globular_crossid = "GCL" in remarks_str or "globular" in remarks_str.lower()
        steinicke_type = (obj.get("object_type") or "").strip()
        # Only objects the globular rescue is eligible to reclassify: a
        # globular cross-ID plus a Roman-numeral concentration class.
        if has_globular_crossid and is_trumpler_class(steinicke_type):
            examined.add((prefix, int(number)))
            mapped = preprocess_steinicke_type(steinicke_type, remarks)
            if mapped != "Gb":
                offenders.append((prefix, int(number), steinicke_type, mapped))

    assert not offenders, (
        "Steinicke objects with a globular cross-ID and concentration-class "
        f"TYPE that were not mapped to 'Gb': {offenders}"
    )
    # Guard against the audit silently inspecting nothing (e.g. a schema change
    # that drops remarks): the known mis-typed globulars must be in scope.
    missing = KNOWN_CONCENTRATION_CLASS_GLOBULARS - examined
    assert not missing, f"Audit did not examine expected globulars: {sorted(missing)}"
