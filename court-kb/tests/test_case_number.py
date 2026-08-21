"""Валидация и приведение номера дела к стандарту."""

from scraper.case_lookup.case_number import (
    normalize_case_number,
    parse_case_number,
    validate_case_number,
)


def test_standard_passthrough():
    assert normalize_case_number("2-1248/2026") == "2-1248/2026"
    assert validate_case_number("2-1248/2026").ok is True


def test_strip_material_tilde():
    assert normalize_case_number("2-1248/2026 ~ М-52/2026") == "2-1248/2026"
    assert normalize_case_number("2-1248/2026~М-52/2026") == "2-1248/2026"
    assert normalize_case_number("2-3588/2026 ~ М-2448/2026") == "2-3588/2026"


def test_strip_delo_prefix_and_number_sign():
    assert normalize_case_number("ДЕЛО № 2-1248/2026") == "2-1248/2026"
    assert normalize_case_number("дело №2-3588/2026") == "2-3588/2026"
    assert normalize_case_number("№ 2-1248/2026") == "2-1248/2026"


def test_full_messy_client_string():
    raw = "ДЕЛО № 2-1248/2026 ~ М-52/2026"
    result = parse_case_number(raw)
    assert result.ok is True
    assert result.normalized == "2-1248/2026"
    assert result.value == "2-1248/2026"


def test_normalize_dashes_and_spaces():
    assert normalize_case_number("2 – 1248 / 2026") == "2-1248/2026"
    assert normalize_case_number("2—1248/2026") == "2-1248/2026"


def test_letter_index():
    assert normalize_case_number("2а-45/2025") == "2а-45/2025"
    assert normalize_case_number("2А-45/2025") == "2а-45/2025"
    assert normalize_case_number("2A-45/2025") == "2а-45/2025"


def test_invalid_empty():
    r = validate_case_number("")
    assert r.ok is False
    assert r.normalized is None
    assert r.error


def test_invalid_garbage():
    r = validate_case_number("просто текст без номера")
    assert r.ok is False
    assert normalize_case_number("просто текст без номера") is None


def test_material_tail_without_tilde():
    assert normalize_case_number("2-1248/2026 М-52/2026") == "2-1248/2026"
