"""Unit tests for the catalog size-string parser (parse_arcmin_size).

These guard the regressions seen during a catalog regen where tokens carrying
unit suffixes (', ", °) or '/' '+' separators were dropped or mangled.
"""

import logging

import pytest

from PiFinder.catalog_imports.catalog_import_utils import parse_arcmin_size


@pytest.mark.unit
def test_empty_string_is_unknown():
    assert parse_arcmin_size("").extents == []


@pytest.mark.unit
def test_bare_number_defaults_to_arcmin():
    # 5 arcmin -> 300 arcsec
    assert parse_arcmin_size("5").extents == pytest.approx([300.0])


@pytest.mark.unit
def test_arcmin_prime_suffix_stripped():
    # Taas200 "32'x6.5'" was previously dropped entirely.
    assert parse_arcmin_size("32'x6.5'").extents == pytest.approx([1920.0, 390.0])


@pytest.mark.unit
def test_arcsec_double_prime_is_arcsec_not_arcmin():
    # EGC "36"" is arcseconds; must NOT be multiplied to arcmin.
    assert parse_arcmin_size('36"').extents == pytest.approx([36.0])
    assert parse_arcmin_size('2.7"').extents == pytest.approx([2.7])


@pytest.mark.unit
def test_degree_suffix():
    # 35° -> 126000 arcsec
    assert parse_arcmin_size("35°").extents == pytest.approx([126000.0])


@pytest.mark.unit
def test_slash_separator():
    # Caldwell "0.3/5.8" -> two arcmin extents.
    assert parse_arcmin_size("0.3/5.8").extents == pytest.approx([18.0, 348.0])


@pytest.mark.unit
def test_plus_separator():
    assert parse_arcmin_size("30'+30'").extents == pytest.approx([1800.0, 1800.0])


@pytest.mark.unit
def test_unicode_times_separator():
    assert parse_arcmin_size("5×3").extents == pytest.approx([300.0, 180.0])


@pytest.mark.unit
def test_truncated_mixed_token_keeps_both_axes():
    # Fixed-width truncation dropped the closing prime: "8.1'x2.6".
    # Previously stored as a round 2.6' object (major axis lost);
    # now both axes survive (8.1' major default-arcmin minor).
    assert parse_arcmin_size("8.1'x2.6").extents == pytest.approx([486.0, 156.0])


@pytest.mark.unit
def test_trailing_dot_float():
    # "13.0'x6." -> 13.0' x 6.0'
    assert parse_arcmin_size("13.0'x6.").extents == pytest.approx([780.0, 360.0])


@pytest.mark.unit
def test_interspersed_word_is_skipped_but_numbers_survive():
    # "30 and 30" warns on 'and' but still yields two extents.
    assert parse_arcmin_size("30 and 30").extents == pytest.approx([1800.0, 1800.0])


@pytest.mark.unit
@pytest.mark.parametrize("raw", ["nl", "n/a", "see Tirion"])
def test_non_numeric_only_is_unknown(raw):
    assert parse_arcmin_size(raw).extents == []


@pytest.mark.unit
def test_non_numeric_token_warns(caplog):
    with caplog.at_level(logging.WARNING):
        parse_arcmin_size("nl")
    assert any("Non-numeric size token" in r.message for r in caplog.records)


@pytest.mark.unit
def test_clean_input_emits_no_warning(caplog):
    with caplog.at_level(logging.WARNING):
        parse_arcmin_size("32'x6.5'")
    assert not any("Non-numeric size token" in r.message for r in caplog.records)
