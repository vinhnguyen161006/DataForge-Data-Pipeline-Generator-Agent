import re

import sqlglot
import sqlglot.expressions as exp

from app.agents.schemas import GeneratedFile

ALLOWED_PREFIXES = ("models/silver/", "models/mart/")
ALLOWED_STATEMENTS = ("select", "with")
ALLOWED_JINJA_CALLS = ("ref", "config", "var")


class GuardViolation(ValueError):
    pass


def check_paths(files: list[GeneratedFile]) -> list[str]:
    violations = []
    seen = set()

    for f in files:
        path = f.path
        if path in seen:
            violations.append(f"Duplicate path {path}")
        seen.add(path)

        if path.startswith("/") or path.startswith("\\") or ".." in path:
            violations.append(f"Invalid relative traversal in path: {path}")

        if not path.endswith(".sql"):
            violations.append(f"Not a .sql file: {path}")

        if not any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            violations.append(f"Path prefix not allowed: {path}")

    return violations


def check_jinja(file: GeneratedFile) -> list[str]:
    violations = []

    if re.search(r"\{%.*?%\}", file.content):
        violations.append(f"Jinja statement blocks not allowed in {file.path}")

    exprs = re.findall(r"\{\{(.*?)\}\}", file.content)
    for expr in exprs:
        calls = re.findall(r"\b([a-zA-Z_]\w*)\s*\(", expr)
        for call in calls:
            if call not in ALLOWED_JINJA_CALLS:
                violations.append(f"Jinja call '{call}' not allowed in {file.path}")

    return violations


def check_sql(file: GeneratedFile) -> list[str]:
    violations = []

    sql = file.content
    sql = re.sub(r"\{\{\s*ref\([^)]+\)\s*\}\}", "dummy_ref_table", sql)
    sql = re.sub(r"\{\{.*?\}\}", " ", sql)
    sql = re.sub(r"\{%.*?%\}", " ", sql)

    try:
        parsed = sqlglot.parse(sql, read="duckdb")
    except Exception as e:
        return [f"SQL parse error in {file.path}: {e}"]

    if not parsed:
        return [f"No statements found in {file.path}"]

    if len(parsed) > 1:
        violations.append(f"Only one query allowed per model in {file.path}")

    ast = parsed[0]
    if ast and ast.key.lower() not in ALLOWED_STATEMENTS:
        violations.append(f"Statement '{ast.key}' not allowed in {file.path}")

    allowed_functions = {
        "sum",
        "count",
        "avg",
        "min",
        "max",
        "coalesce",
        "cast",
        "concat",
        "round",
        "lower",
        "upper",
        "trim",
        "abs",
        "extract",
        "date_trunc",
        "row_number",
        "rank",
        "dense_rank",
        "lead",
        "lag",
        "nullif",
        "ifnull",
        "substring",
        "replace",
        "split",
        "length",
        "strpos",
        "left",
        "right",
        "lpad",
        "rpad",
        "string_agg",
        "array_agg",
        "any_value",
        "greatest",
        "least",
        "try_cast",
        "typeof",
        "floor",
        "ceil",
        "exp",
        "ln",
        "log",
        "power",
        "sqrt",
        "sign",
        "date_add",
        "date_sub",
        "date_diff",
        "regexp_matches",
        "regexp_extract",
        "regexp_replace",
        "list_extract",
        "unnest",
        "generate_series",
        "strftime",
        "strptime",
        "first_value",
        "last_value",
        "nth_value",
        "stddev",
        "variance",
        "approx_count_distinct",
    }

    allowed_node_keys = {
        "select",
        "from",
        "where",
        "group",
        "having",
        "order",
        "limit",
        "offset",
        "join",
        "with",
        "cte",
        "alias",
        "column",
        "table",
        "identifier",
        "literal",
        "star",
        "boolean",
        "null",
        "cast",
        "try_cast",
        "extract",
        "case",
        "ifs",
        "coalesce",
        "nullif",
        "window",
        "partition",
        "sort",
        "count",
        "sum",
        "avg",
        "min",
        "max",
        "stddev",
        "variance",
        "any_value",
        "row_number",
        "rank",
        "dense_rank",
        "lead",
        "lag",
        "first_value",
        "last_value",
        "nth_value",
        "concat",
        "substring",
        "lower",
        "upper",
        "trim",
        "length",
        "replace",
        "abs",
        "round",
        "floor",
        "ceil",
        "datatype",
        "windowspec",
        "paren",
        "tuple",
        "struct",
        "array",
        "array_agg",
        "string_agg",
        "map",
        "var_map",
        "regexp_like",
        "regexp_ilike",
        "anonymous",
        "func",
        "bracket",
        "values",
        "unnest",
        "filter",
        "subquery",
        "union",
        "intersect",
        "except",
        "dot",
        "kwarg",
        "interval",
        "date_add",
        "date_sub",
        "date_diff",
        "date_trunc",
        "str_to_date",
        "str_to_time",
        "unix_to_time",
        "time_to_unix",
        "add",
        "sub",
        "mul",
        "div",
        "mod",
        "and",
        "or",
        "not",
        "eq",
        "neq",
        "lt",
        "lte",
        "gt",
        "gte",
        "is",
        "in",
        "between",
        "like",
        "ilike",
        "json_extract",
        "generate_series",
        "str_position",
        "query",
        "ordered",
        "on",
        "using",
        "convert",
        "datetime_add",
        "datetime_sub",
        "datetime_diff",
        "datetime_trunc",
        "time_add",
        "time_sub",
        "time_diff",
        "time_trunc",
        "ts_or_ds_add",
        "ts_or_ds_to_date",
        "ts_or_ds_diff",
        "ts_or_ds_trunc",
        "approx_distinct",
        "bit_and",
        "bit_or",
        "bit_xor",
        "bool_and",
        "bool_or",
        "corr",
        "covar_pop",
        "covar_samp",
        "every",
        "kurtosis",
        "mad",
        "median",
        "mode",
        "skewness",
        "stddev_pop",
        "stddev_samp",
        "var_pop",
        "var_samp",
        "list_extract",
        "list_value",
        "current_row",
        "window_frame",
        "expression",
    }

    if ast:
        for node in ast.walk():
            actual_node = node

            if actual_node.key.lower() not in allowed_node_keys:
                violations.append(f"AST node '{actual_node.key}' not allowed in {file.path}")

            if isinstance(actual_node, exp.Table) and not isinstance(
                actual_node.this, exp.Identifier
            ):
                violations.append(f"Table function not allowed in {file.path}")

            if isinstance(actual_node, (exp.Func, exp.Anonymous)):
                func_name = actual_node.name.lower() if hasattr(actual_node, "name") else ""
                if func_name and func_name not in allowed_functions:
                    violations.append(f"Function '{func_name}' not allowed in {file.path}")

    return violations


def check_generated_files(files: list[GeneratedFile]) -> list[str]:
    violations = check_paths(files)
    for f in files:
        violations.extend(check_jinja(f))
        violations.extend(check_sql(f))
    return violations
