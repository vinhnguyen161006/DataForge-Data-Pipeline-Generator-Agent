import pytest


@pytest.mark.skip(reason="TODO")
def test_same_rows_different_order_are_equivalent() -> None:
    """TODO: order must not matter."""


@pytest.mark.skip(reason="TODO")
def test_same_row_count_different_multiplicity_is_not_equivalent() -> None:
    """TODO: [a, a, b] vs [a, b, b] must differ although row counts match."""


@pytest.mark.skip(reason="TODO")
def test_nulls_compare_equal() -> None:
    """TODO: NULL rows on both sides are equivalent."""


@pytest.mark.skip(reason="TODO")
def test_float_tolerance() -> None:
    """TODO: 0.1 + 0.2 and 0.3 are equivalent after rounding."""


@pytest.mark.skip(reason="TODO")
def test_schema_mismatch() -> None:
    """TODO: different column names or types are never equivalent."""


@pytest.mark.skip(reason="TODO")
def test_improvement_within_noise_is_not_faster() -> None:
    """TODO: is_faster() requires improvement above threshold and noise."""
