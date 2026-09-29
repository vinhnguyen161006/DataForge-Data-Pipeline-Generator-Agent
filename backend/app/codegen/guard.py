from app.agents.schemas import GeneratedFile

ALLOWED_PREFIXES = ("models/silver/", "models/mart/")

ALLOWED_STATEMENTS = ("select", "with")

ALLOWED_JINJA_CALLS = ("ref", "config", "var")


class GuardViolation(ValueError):
    pass


def check_paths(files: list[GeneratedFile]) -> list[str]:
    """TODO: reject absolute paths, "..", duplicates, non-.sql files and other prefixes.

    Only paths under ALLOWED_PREFIXES are accepted.
    """
    raise NotImplementedError


def check_jinja(file: GeneratedFile) -> list[str]:
    """TODO: allowlist Jinja: only ALLOWED_JINJA_CALLS; no run_query, env_var, statement blocks."""
    raise NotImplementedError


def check_sql(file: GeneratedFile) -> list[str]:
    """TODO: parse the Jinja-stripped SQL with sqlglot (duckdb) and allowlist the AST.

    Only one ALLOWED_STATEMENTS query per model. Reject table functions that touch
    files or network (read_csv, read_parquet, glob, ...), and nondeterministic
    functions (now, current_date, random, uuid). Allowlist, never denylist.
    """
    raise NotImplementedError


def check_generated_files(files: list[GeneratedFile]) -> list[str]:
    """TODO: run check_paths, check_jinja and check_sql; return every violation.

    Defense in depth only: the security boundary is the sandbox worker.
    """
    raise NotImplementedError
