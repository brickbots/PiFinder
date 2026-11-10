"""
The observing-list lookup reads a designation the way the catalog import does.

Fault 6 of the review on #670: the lookup had its own parser, so "H 24" (a
double star) resolved to Herschel 400 #24, "Cr 399" resolved to nothing and
"Collinder 399" resolved to a Lyngå object. Both now ask
PiFinder.designations, and the name lookup keeps #673's cases.

The fake catalog below copies the relevant rows of the catalog database: the
names "H 24" and "h 99" come from the SAC double-star listings, and the Lyngå
object carries the name "Collinder 399".
"""

import ast
import inspect
import json
from types import SimpleNamespace

import pytest

from PiFinder import designations, obslist
from PiFinder.catalog_imports import catalog_import_utils
from PiFinder.obslist_formats import ObsList, ObsListEntry, write_skylist


def _obj(label, *names):
    return SimpleNamespace(label=label, names=list(names), list_descriptions={})


COL_399 = _obj("Col 399", "Col 399", "Brocchi's Cluster", "Ta2 173")
LYN_847 = _obj("Lyn 847", "Collinder 399")
NGC_5676 = _obj("NGC 5676", "NGC 5676", "H I 189")
H400_99 = _obj("NGC 4027", "NGC 4027", "H II 296")
SAM_137 = _obj("SaM 137", "SaM 137", "107 Aqr", "H 24")
SAM_999 = _obj("SaM 999", "SaM 999", "h 99")
M_29 = _obj("M 29", "M 29", "NGC 6913")
MINKOWSKI_2_9 = _obj("M 2-9", "M 2-9", "Minkowski's Butterfly")
NGC_497 = _obj("NGC 497", "NGC 497")
ARP_8 = _obj("Arp 8", "Arp 8", "NGC 0497 group")
SH2_155 = _obj("Sh2 155", "Sh2 155", "Cave Nebula")
BARNARD_33 = _obj("B 33", "B 33", "Horsehead Nebula")
WDS_10423 = _obj("WDS 10423", "B 33")
C_14 = _obj("C 14", "C 14", "Double Cluster")
VY_AND = _obj("SaR 7", "VY And")

LISTINGS = {
    ("Col", 399): COL_399,
    ("Ta2", 173): COL_399,
    ("Lyn", 847): LYN_847,
    ("NGC", 5676): NGC_5676,
    ("H", 24): NGC_5676,
    ("NGC", 4027): H400_99,
    ("H", 99): H400_99,
    ("SaM", 137): SAM_137,
    ("SaM", 999): SAM_999,
    ("M", 29): M_29,
    ("NGC", 6913): M_29,
    ("NGC", 497): NGC_497,
    ("Arp", 8): ARP_8,
    ("Sh2", 155): SH2_155,
    ("B", 33): BARNARD_33,
    ("WDS", 10423): WDS_10423,
    ("C", 14): C_14,
    ("SaR", 7): VY_AND,
}


class FakeCatalogs:
    def get_object(self, catalog_code, sequence):
        return LISTINGS.get((catalog_code, sequence))

    def get_objects(self, only_selected=True, filtered=True):
        # The Minkowski nebula has no PiFinder listing; it resolves by name only.
        objects = [MINKOWSKI_2_9]
        for obj in LISTINGS.values():
            if obj not in objects:
                objects.append(obj)
        return objects


def _resolve(tmp_path, monkeypatch, filename, text):
    """Load one observing list file and return the labels it resolved to."""
    monkeypatch.setattr(obslist, "OBSLIST_DIR", str(tmp_path))
    (tmp_path / filename).write_text(text)
    result = obslist.read_list(FakeCatalogs(), filename)
    assert result["result"] == "success"
    return [obj.label for obj in result["catalog_objects"]]


def _resolve_name(tmp_path, monkeypatch, name):
    """The label one plain-text name resolves to, or None."""
    labels = _resolve(tmp_path, monkeypatch, "list.txt", name + "\n")
    return labels[0] if labels else None


@pytest.mark.unit
@pytest.mark.parametrize(
    "name, expected",
    [
        # A bare "H" or "h" is a double-star discoverer, not Herschel 400.
        ("H 24", None),
        ("h 99", None),
        ("H24", None),
        # Every spelling of Collinder names the "Col" catalog.
        ("Cr 399", "Col 399"),
        ("Collinder 399", "Col 399"),
        ("Col 399", "Col 399"),
        ("Caldwell 14", "C 14"),
        ("C 14", "C 14"),
        # #673's cases: a compound number is not a Messier number, and a
        # leading zero does not change the number.
        ("M 2-9", "M 2-9"),
        ("M 29", "M 29"),
        ("NGC 0497", "NGC 497"),
        ("Sh2-155", "Sh2 155"),
        ("Sh 2-155", "Sh2 155"),
        ("Sh2 155", "Sh2 155"),
        # Common names still resolve by name.
        ("Cave Nebula", "Sh2 155"),
        ("VY Andromedae", "SaR 7"),
        # "B 33" is Barnard 33 and van den Bos 33; "Barnard 33" is not.
        ("B 33", None),
        ("Barnard 33", "B 33"),
    ],
)
def test_plain_text_names(tmp_path, monkeypatch, name, expected):
    assert _resolve_name(tmp_path, monkeypatch, name) == expected


@pytest.mark.unit
def test_compound_designation_with_no_object_is_not_messier(tmp_path, monkeypatch):
    # With no Minkowski object to match by name, "M 2-9" resolves to nothing,
    # never to M 29.
    monkeypatch.setattr(FakeCatalogs, "get_objects", lambda self, **kw: [M_29])
    assert _resolve_name(tmp_path, monkeypatch, "M 2-9") is None


@pytest.mark.unit
def test_skylist_catalog_numbers(tmp_path, monkeypatch):
    text = (
        "SkySafariObservingListVersion=3.0\n"
        "SkyObject=BeginObject\n  CatalogNumber=Cr 399\nEndObject=SkyObject\n"
        "SkyObject=BeginObject\n  CatalogNumber=H 24\nEndObject=SkyObject\n"
        # The first catalog number names nothing; the second resolves.
        "SkyObject=BeginObject\n  CatalogNumber=h 99\n  CatalogNumber=NGC 4027\n"
        "EndObject=SkyObject\n"
    )
    assert _resolve(tmp_path, monkeypatch, "list.skylist", text) == [
        "Col 399",
        "NGC 4027",
    ]


@pytest.mark.unit
def test_csv_catalog_columns_use_the_same_parser(tmp_path, monkeypatch):
    text = (
        "Name,RA,Dec,CatalogCode,Sequence\n"
        "Coathanger,,,Collinder,399\n"
        "Double star,,,H,24\n"
        "Cr 399,,,,\n"
    )
    assert _resolve(tmp_path, monkeypatch, "list.csv", text) == [
        "Col 399",
        "Col 399",
    ]


@pytest.mark.unit
def test_native_format_catalog_key_is_exact(tmp_path, monkeypatch):
    # The native format stores PiFinder's own catalog key, so "H" here is
    # Herschel 400 by definition.
    text = json.dumps(
        {
            "version": 1,
            "name": "native",
            "objects": [
                {"catalog_code": "H", "sequence": 24},
                {"catalog_code": "Col", "sequence": 399},
            ],
        }
    )
    assert _resolve(tmp_path, monkeypatch, "list.pifinder", text) == [
        "NGC 5676",
        "Col 399",
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "name, expected",
    [
        ("H 24", True),
        ("h 99", True),
        ("h99", True),
        ("A 58", True),
        ("B 33", True),
        ("H 1-1", False),
        ("H II 296", False),
        ("Barnard 33", False),
        ("NGC 224", False),
        ("Andromeda", False),
    ],
)
def test_is_ambiguous_designation(name, expected):
    assert designations.is_ambiguous_designation(name) is expected


@pytest.mark.unit
def test_import_reexports_the_one_parser():
    assert catalog_import_utils.parse_designation is designations.parse_designation
    assert catalog_import_utils.listing_named is designations.listing_named
    assert (
        catalog_import_utils.CATALOG_CODE_ALIASES is designations.CATALOG_CODE_ALIASES
    )


@pytest.mark.unit
def test_designations_is_runtime_safe():
    # The running app imports it, so it must not pull in the catalog import
    # (tqdm, the import databases) or anything else outside the standard library.
    tree = ast.parse(inspect.getsource(designations))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported <= {"re", "typing"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "code, sequence, expected",
    [
        ("Col", 399, "Col 399"),
        ("NGC", 224, "NGC 224"),
        ("Sh2", 155, "Sh2 155"),
        ("H", 24, "Herschel 24"),
        ("B", 33, "Barnard 33"),
        ("Nam", 91262, "Nam 91262"),
        ("WDS", 50812, None),
    ],
)
def test_designation_reads_back(code, sequence, expected):
    assert designations.designation(code, sequence) == expected
    if expected:
        assert designations.listing_named(expected) == (code, sequence)


@pytest.mark.unit
def test_saved_skylist_round_trips_herschel_and_barnard(tmp_path, monkeypatch):
    # PiFinder saves lists as SkySafari files. A Herschel 400 or Barnard
    # object must come back as the same object, not as a double star.
    entries = [
        ObsListEntry(
            name="NGC 5676", ra=218.2, dec=49.5, catalog_code="H", sequence=24
        ),
        ObsListEntry(name="B 33", ra=85.2, dec=-2.5, catalog_code="B", sequence=33),
        ObsListEntry(
            name="Col 399", ra=291.3, dec=20.2, catalog_code="Col", sequence=399
        ),
    ]
    text = write_skylist(ObsList(name="saved", entries=entries))
    assert "CatalogNumber=Herschel 24" in text
    assert "CatalogNumber=Barnard 33" in text
    assert _resolve(tmp_path, monkeypatch, "saved.skylist", text) == [
        "NGC 5676",
        "B 33",
        "Col 399",
    ]
