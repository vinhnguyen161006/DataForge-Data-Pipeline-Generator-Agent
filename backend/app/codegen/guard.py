import ast
import re
from pathlib import PurePosixPath

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.agents.schemas import GeneratedFile

ALLOWED_PREFIXES = ("models/silver/", "models/mart/")

ALLOWED_STATEMENTS = ("select", "with")

ALLOWED_JINJA_CALLS = ("ref", "config", "var")

FORBIDDEN_CONFIG_KEYS = frozenset(
    {
        "pre_hook",
        "post_hook",
        "pre-hook",
        "post-hook",
        "sql_header",
    }
)

ALLOWED_SQL_FUNCTIONS = frozenset(
    {
        "abs",
        "acos",
        "array_agg",
        "array_length",
        "asin",
        "atan",
        "atan2",
        "avg",
        "bool_and",
        "bool_or",
        "case",
        "cast",
        "ceil",
        "ceiling",
        "chr",
        "coalesce",
        "concat",
        "concat_ws",
        "corr",
        "cos",
        "count",
        "count_if",
        "covar_pop",
        "covar_samp",
        "cume_dist",
        "date",
        "date_add",
        "date_diff",
        "date_part",
        "date_sub",
        "date_trunc",
        "datediff",
        "datepart",
        "datetrunc",
        "day",
        "dayname",
        "dayofmonth",
        "dayofweek",
        "dayofyear",
        "dense_rank",
        "epoch",
        "exp",
        "extract",
        "first",
        "first_value",
        "floor",
        "format",
        "greatest",
        "hash",
        "hour",
        "if",
        "iff",
        "ifnull",
        "initcap",
        "instr",
        "isnan",
        "isinf",
        "julian",
        "lag",
        "last",
        "last_day",
        "last_value",
        "lead",
        "least",
        "left",
        "length",
        "list",
        "list_agg",
        "ln",
        "log",
        "log10",
        "log2",
        "lower",
        "lpad",
        "ltrim",
        "make_date",
        "make_timestamp",
        "max",
        "md5",
        "median",
        "min",
        "minute",
        "mod",
        "month",
        "monthname",
        "next_value",
        "nth_value",
        "ntile",
        "nullif",
        "nvvl",
        "octet_length",
        "percent_rank",
        "percentile_cont",
        "percentile_disc",
        "pi",
        "position",
        "pow",
        "power",
        "printf",
        "quantile_cont",
        "quantile_disc",
        "quarter",
        "radians",
        "rank",
        "regexp_extract",
        "regexp_matches",
        "regexp_replace",
        "regexp_split_to_array",
        "repeat",
        "replace",
        "reverse",
        "right",
        "round",
        "row_number",
        "rpad",
        "rtrim",
        "second",
        "sha256",
        "sign",
        "sin",
        "split_part",
        "sqrt",
        "stddev",
        "stddev_pop",
        "stddev_samp",
        "str_split",
        "strftime",
        "string_agg",
        "string_split",
        "strpos",
        "strptime",
        "strtodate",
        "strtotime",
        "struct_pack",
        "substr",
        "substring",
        "sum",
        "tan",
        "time_bucket",
        "timetostr",
        "to_char",
        "to_date",
        "to_timestamp",
        "translate",
        "trim",
        "trunc",
        "try_cast",
        "upper",
        "var_pop",
        "var_samp",
        "variance",
        "week",
        "weekday",
        "weekofyear",
        "year",
    }
)

FORBIDDEN_SQL_FUNCTIONS = frozenset(
    {
        "current_date",
        "current_time",
        "current_timestamp",
        "currentdate",
        "currenttime",
        "currenttimestamp",
        "gen_random_uuid",
        "glob",
        "iceberg_scan",
        "localtime",
        "localtimestamp",
        "now",
        "parquet_scan",
        "postgres_scan",
        "random",
        "read_blob",
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_ndjson",
        "read_parquet",
        "read_text",
        "sqlite_scan",
        "today",
        "transaction_timestamp",
        "uuid",
        "uuidv4",
        "uuidv7",
    }
)

FILE_EXTENSIONS = (
    ".csv",
    ".parquet",
    ".json",
    ".jsonl",
    ".ndjson",
    ".db",
    ".duckdb",
    ".sqlite",
    ".tsv",
    ".txt",
    ".gz",
    ".zip",
)

JINJA_EXPR_PATTERN = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


class GuardViolation(ValueError):
    pass


def check_paths(files: list[GeneratedFile]) -> list[str]:
    """Reject absolute paths, '..', duplicates, non-.sql files and other prefixes.

    Only paths under ALLOWED_PREFIXES are accepted.
    """
    violations: list[str] = []
    seen: set[str] = set()

    for file in files:
        path = file.path
        segments = path.split("/")

        if not path or path != path.strip():
            violations.append(f"{path}: empty or whitespace-padded path is not allowed")
            continue

        if path.startswith(("/", "\\")) or "\\" in path or ":" in path:
            violations.append(f"{path}: absolute or backslash path is not allowed")

        if ".." in segments or "." in segments or "" in segments:
            violations.append(f"{path}: relative traversal segments are not allowed")

        if not path.startswith(ALLOWED_PREFIXES):
            violations.append(f"{path}: path must start with {ALLOWED_PREFIXES}")

        if not path.endswith(".sql") or PurePosixPath(path).stem == "":
            violations.append(f"{path}: path must be a valid .sql file")

        if path in seen:
            violations.append(f"{path}: duplicate file path")
        seen.add(path)

    return violations


def _is_safe_literal_node(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(
            child,
            (
                ast.Constant,
                ast.List,
                ast.Tuple,
                ast.Dict,
                ast.Load,
                ast.UnaryOp,
                ast.USub,
                ast.UAdd,
            ),
        ):
            return False
    return True


def check_jinja(file: GeneratedFile) -> list[str]:
    """Allowlist Jinja: only ALLOWED_JINJA_CALLS; no run_query, env_var, statement blocks."""
    violations: list[str] = []
    content = file.content

    if "{%" in content or "%}" in content:
        violations.append(f"{file.path}: Jinja statement blocks are not allowed")

    if "{#" in content or "#}" in content:
        violations.append(f"{file.path}: Jinja comment blocks are not allowed")

    if content.count("{{") != content.count("}}"):
        violations.append(f"{file.path}: unbalanced Jinja expression delimiters")

    for match in JINJA_EXPR_PATTERN.finditer(content):
        raw_expr = match.group(1).strip()
        if not raw_expr:
            violations.append(f"{file.path}: empty Jinja expression is not allowed")
            continue

        try:
            parsed = ast.parse(raw_expr, mode="eval")
        except SyntaxError:
            violations.append(f"{file.path}: invalid Jinja expression '{raw_expr}'")
            continue

        body = parsed.body
        if not isinstance(body, ast.Call) or not isinstance(body.func, ast.Name):
            violations.append(
                f"{file.path}: Jinja expression '{raw_expr}' must be a direct function call"
            )
            continue

        func_name = body.func.id
        if func_name not in ALLOWED_JINJA_CALLS:
            violations.append(
                f"{file.path}: Jinja call '{func_name}' is not in allowlist {ALLOWED_JINJA_CALLS}"
            )
            continue

        for arg in body.args:
            if not _is_safe_literal_node(arg):
                violations.append(
                    f"{file.path}: Jinja call '{func_name}' has non-literal positional argument"
                )

        for kw in body.keywords:
            if kw.arg is None or not _is_safe_literal_node(kw.value):
                violations.append(
                    f"{file.path}: Jinja call '{func_name}' has disallowed keyword argument"
                )
            elif func_name == "config" and kw.arg.lower() in FORBIDDEN_CONFIG_KEYS:
                violations.append(
                    f"{file.path}: config key '{kw.arg}' is not allowed"
                )

    return violations


def _strip_jinja_for_sql(content: str) -> str:
    def _replace_expr(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        if inner.startswith("config"):
            return ""
        return "__dbt_ref_placeholder"

    without_blocks = re.sub(r"\{%.*?%\}", "", content, flags=re.DOTALL)
    without_comments = re.sub(r"\{#.*?#\}", "", without_blocks, flags=re.DOTALL)
    return JINJA_EXPR_PATTERN.sub(_replace_expr, without_comments)


def _check_table_node(path: str, table: exp.Table) -> list[str]:
    violations: list[str] = []
    table_this = table.this

    if not isinstance(table_this, exp.Identifier):
        violations.append(
            f"{path}: table source '{table.sql(dialect='duckdb')}' must be a plain identifier"
        )
        return violations

    name_lower = table.name.lower()
    if (
        name_lower.endswith(FILE_EXTENSIONS)
        or "/" in name_lower
        or "\\" in name_lower
        or "://" in name_lower
        or name_lower in FORBIDDEN_SQL_FUNCTIONS
    ):
        violations.append(f"{path}: table source '{table.name}' accesses external files")

    if table.catalog:
        violations.append(f"{path}: cross-catalog reference '{table.catalog}' is not allowed")

    return violations


def _check_function_node(path: str, func: exp.Func) -> list[str]:
    candidates = {
        func.sql_name().lower(),
        func.key.lower(),
    }
    if isinstance(func, exp.Anonymous):
        candidates.add(func.name.lower())

    if candidates & FORBIDDEN_SQL_FUNCTIONS:
        func_label = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
        return [f"{path}: forbidden SQL function '{func_label}'"]

    if not (candidates & ALLOWED_SQL_FUNCTIONS):
        func_label = func.name if isinstance(func, exp.Anonymous) else func.sql_name()
        return [f"{path}: SQL function '{func_label}' is not in allowlist"]

    return []


def check_sql(file: GeneratedFile) -> list[str]:
    """Parse the Jinja-stripped SQL with sqlglot (duckdb) and allowlist the AST.

    Only one ALLOWED_STATEMENTS query per model. Reject table functions that touch
    files or network (read_csv, read_parquet, glob, ...), and nondeterministic
    functions (now, current_date, random, uuid). Allowlist, never denylist.
    """
    violations: list[str] = []
    stripped_sql = _strip_jinja_for_sql(file.content).strip()

    if not stripped_sql:
        return [f"{file.path}: SQL content is empty"]

    first_token_match = re.match(r"^([a-zA-Z_]+)", stripped_sql)
    first_keyword = first_token_match.group(1).lower() if first_token_match else ""
    if first_keyword not in ALLOWED_STATEMENTS:
        violations.append(
            f"{file.path}: statement must start with {ALLOWED_STATEMENTS}, got '{first_keyword}'"
        )

    try:
        parsed = [
            stmt
            for stmt in sqlglot.parse(stripped_sql, read="duckdb")
            if stmt is not None
        ]
    except SqlglotError as exc:
        violations.append(f"{file.path}: invalid DuckDB SQL: {exc}")
        return violations

    if len(parsed) != 1:
        violations.append(
            f"{file.path}: expected exactly 1 SQL statement, got {len(parsed)}"
        )
        return violations

    statement = parsed[0]
    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        violations.append(
            f"{file.path}: root statement '{statement.key}' is not a SELECT query"
        )
        return violations

    for node in statement.find_all(exp.Expression):
        if isinstance(node, exp.Table):
            violations.extend(_check_table_node(file.path, node))
        elif isinstance(node, exp.Func):
            violations.extend(_check_function_node(file.path, node))

    return violations


def check_generated_files(files: list[GeneratedFile]) -> list[str]:
    """Run check_paths, check_jinja and check_sql; return every violation.

    Defense in depth only: the security boundary is the sandbox worker.
    """
    violations = check_paths(files)
    for file in files:
        violations.extend(check_jinja(file))
        violations.extend(check_sql(file))
    return violations