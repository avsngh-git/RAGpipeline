from research_platform.validation import validate_year_range


def test_accepts_increasing_years() -> None:
    assert validate_year_range(2020, 2026)


def test_accepts_same_year() -> None:
    assert validate_year_range(2020, 2020)


def test_rejects_reversed_years() -> None:
    assert not validate_year_range(2026, 2020)
