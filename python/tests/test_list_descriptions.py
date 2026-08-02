"""
Tests for multi-source object descriptions: a CompositeObject's own catalog
description plus per-observing-list descriptions, aggregated into one rendered
string.

This is the obslist "testing ground" for showing every list's description of an
object that appears in several lists.

Section headers are built with `_section_header` rather than hardcoded dashes,
so the separator style/length can change without touching these tests.
"""

import pytest

from PiFinder.composite_object import CompositeObject, _section_header


@pytest.mark.unit
def test_labeled_descriptions_first_then_home_description():
    obj = CompositeObject(
        object_id=1, catalog_code="NGC", sequence=224, description="Andromeda Galaxy"
    )
    obj.list_descriptions["Autumn Targets"] = "naked eye from the cabin"
    obj.list_descriptions["Messier Best"] = "start here"
    assert obj.composed_description() == (
        f"{_section_header('Autumn Targets')}\n"
        "naked eye from the cabin\n"
        f"{_section_header('Messier Best')}\n"
        "start here\n"
        f"{_section_header('NGC 224')}\n"
        "Andromeda Galaxy"
    )


@pytest.mark.unit
def test_descriptions_render_in_insertion_order():
    obj = CompositeObject(object_id=1, description="home")
    for name in ("B", "A", "C"):
        obj.list_descriptions[name] = name.lower()
    out = obj.composed_description()
    assert (
        out.index(_section_header("B"))
        < out.index(_section_header("A"))
        < out.index(_section_header("C"))
    )


@pytest.mark.unit
def test_empty_home_description_shows_only_list_descriptions():
    obj = CompositeObject(object_id=1, description="")
    obj.list_descriptions["L"] = "from the list"
    assert obj.composed_description() == f"{_section_header('L')}\nfrom the list"


@pytest.mark.unit
def test_no_list_descriptions_is_just_the_description():
    obj = CompositeObject(object_id=1, description="solo")
    assert obj.composed_description() == "solo"


@pytest.mark.unit
def test_composed_sections_structure():
    obj = CompositeObject(
        object_id=1, catalog_code="NGC", sequence=224, description="home"
    )
    obj.list_descriptions["My List"] = "from the list"
    secs = obj.composed_sections(extra_descriptions={"M 1": "other"})
    assert secs == [("My List", "from the list"), ("NGC 224", "home"), ("M 1", "other")]


@pytest.mark.unit
def test_home_unlabeled_when_no_list_description_precedes():
    # Home leads unlabeled even with other catalogs after it; only a preceding
    # observing list description promotes it to its own designator-labeled section.
    obj = CompositeObject(
        object_id=1, catalog_code="NGC", sequence=224, description="home"
    )
    secs = obj.composed_sections(extra_descriptions={"M 1": "other"})
    assert secs == [(None, "home"), ("M 1", "other")]


@pytest.mark.unit
def test_reloading_a_list_overwrites_its_own_description():
    # A list name is the key, so re-loading it replaces (never duplicates) it.
    obj = CompositeObject(object_id=1, description="home")
    obj.list_descriptions["L"] = "first"
    obj.list_descriptions["L"] = "second"
    out = obj.composed_description()
    assert out.count(_section_header("L")) == 1
    assert "second" in out and "first" not in out


@pytest.mark.unit
def test_list_descriptions_is_per_instance():
    # Guards against a shared mutable default.
    a = CompositeObject(object_id=1)
    b = CompositeObject(object_id=2)
    a.list_descriptions["L"] = "x"
    assert b.list_descriptions == {}


# cross-catalog descriptions


@pytest.mark.unit
def test_extra_catalog_descriptions_after_home():
    obj = CompositeObject(
        object_id=869, catalog_code="NGC", sequence=869, description="! Cl, vvL"
    )
    extra = {"Col 24": "250 stars", "Lyn 69": "Age: 18 Myr"}
    assert obj.composed_description(extra_descriptions=extra) == (
        "! Cl, vvL\n"
        f"{_section_header('Col 24')}\n"
        "250 stars\n"
        f"{_section_header('Lyn 69')}\n"
        "Age: 18 Myr"
    )


@pytest.mark.unit
def test_extra_description_identical_to_home_is_deduped():
    # M-listings often copy the NGC text; identical text is dropped.
    obj = CompositeObject(object_id=224, catalog_code="NGC", description="Andromeda")
    out = obj.composed_description(extra_descriptions={"M 31": "Andromeda"})
    assert out == "Andromeda"
    assert _section_header("M 31") not in out


@pytest.mark.unit
def test_extra_description_dedup_can_be_disabled():
    obj = CompositeObject(object_id=224, catalog_code="NGC", description="Andromeda")
    out = obj.composed_description(
        extra_descriptions={"M 31": "Andromeda"}, dedup=False
    )
    assert out == f"Andromeda\n{_section_header('M 31')}\nAndromeda"


@pytest.mark.unit
def test_list_descriptions_then_home_then_extra_catalogs():
    obj = CompositeObject(
        object_id=1, catalog_code="NGC", sequence=224, description="home"
    )
    obj.list_descriptions["My List"] = "go see it"
    out = obj.composed_description(extra_descriptions={"M 1": "other catalog"})
    assert out == (
        f"{_section_header('My List')}\n"
        "go see it\n"
        f"{_section_header('NGC 224')}\n"
        "home\n"
        f"{_section_header('M 1')}\n"
        "other catalog"
    )
