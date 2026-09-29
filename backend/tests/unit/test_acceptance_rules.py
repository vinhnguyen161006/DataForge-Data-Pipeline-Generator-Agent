import pytest


@pytest.mark.skip(reason="TODO")
def test_faster_rewrite_that_changes_result_is_rejected() -> None:
    """TODO: judge() returns WRONG_RESULT and select_best() keeps the original SQL."""


@pytest.mark.skip(reason="TODO")
def test_code_edit_after_approval_invalidates_approval() -> None:
    """TODO: changing code_hash makes assert_approval_matches raise StaleApprovalError."""
