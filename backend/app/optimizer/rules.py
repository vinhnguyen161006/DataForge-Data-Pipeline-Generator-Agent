from sqlglot import exp


def parse(sql: str) -> exp.Expression:
    """TODO: parse compiled SQL with sqlglot using the duckdb dialect."""
    raise NotImplementedError


def normalize(sql: str) -> str:
    """TODO: pretty-print SQL in the duckdb dialect so candidates can be deduplicated."""
    raise NotImplementedError


def rule_based_candidates(sql: str) -> list[tuple[str, str]]:
    """TODO: return [(rule name, candidate SQL)] from sqlglot rewrites.

    Candidates go through the same judge as LLM proposals.
    """
    raise NotImplementedError
