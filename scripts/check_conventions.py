"""Enforce the CLAUDE.md code conventions: no comments and ASCII-only code files."""

import io
import re
import sys
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "node_modules",
        "dist",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "docs",
        "prompts",
        "golden",
        "data",
    }
)
SKIPPED_FILES = frozenset({"uv.lock", "package-lock.json"})

HASH_COMMENT_SUFFIXES = frozenset(
    {".yml", ".yaml", ".toml", ".sh", ".ini", ".cfg", ".txt", ".in", ".mako"}
)
HASH_COMMENT_NAMES = frozenset({"Dockerfile", ".dockerignore", ".gitignore", ".python-version"})
SLASH_COMMENT_SUFFIXES = frozenset({".ts", ".tsx", ".js", ".mjs", ".css"})
SQL_SUFFIXES = frozenset({".sql", ".j2"})
ASCII_ONLY_SUFFIXES = (
    HASH_COMMENT_SUFFIXES
    | SLASH_COMMENT_SUFFIXES
    | SQL_SUFFIXES
    | {".py", ".json", ".html", ".example"}
)

STRING_LITERAL = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|`(?:[^`\\]|\\.)*`")
HASH_COMMENT = re.compile(r"(^|\s)#")
SLASH_COMMENT = re.compile(r"//|/\*")
SQL_COMMENT = re.compile(r"--|/\*|\{#")


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path.relative_to(REPO_ROOT).as_posix()}:{self.line}: {self.message}"


def iter_code_files(root: Path) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name in SKIPPED_FILES:
            continue
        if SKIPPED_DIRS.intersection(path.relative_to(root).parts[:-1]):
            continue
        if path.suffix in ASCII_ONLY_SUFFIXES or path.suffix == ".py" or is_hash_file(path):
            yield path


def is_hash_file(path: Path) -> bool:
    return path.suffix in HASH_COMMENT_SUFFIXES or path.name in HASH_COMMENT_NAMES


def is_shebang(line_number: int, line: str) -> bool:
    return line_number == 1 and line.startswith("#!")


def python_comments(path: Path, source: str) -> Iterator[Violation]:
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        line_number = token.start[0]
        if token.type == tokenize.COMMENT and not is_shebang(line_number, token.string):
            yield Violation(path, line_number, "comment is not allowed")


def pattern_comments(path: Path, source: str, pattern: re.Pattern[str]) -> Iterator[Violation]:
    for line_number, line in enumerate(source.splitlines(), start=1):
        if is_shebang(line_number, line):
            continue
        if pattern.search(STRING_LITERAL.sub("''", line)):
            yield Violation(path, line_number, "comment is not allowed")


def comment_violations(path: Path, source: str) -> Iterator[Violation]:
    if path.suffix == ".py":
        yield from python_comments(path, source)
    elif is_hash_file(path):
        yield from pattern_comments(path, source, HASH_COMMENT)
    elif path.suffix in SLASH_COMMENT_SUFFIXES:
        yield from pattern_comments(path, source, SLASH_COMMENT)
    elif path.suffix in SQL_SUFFIXES:
        yield from pattern_comments(path, source, SQL_COMMENT)


def ascii_violations(path: Path, source: str) -> Iterator[Violation]:
    for line_number, line in enumerate(source.splitlines(), start=1):
        if not line.isascii():
            yield Violation(path, line_number, "non-ASCII character in code file")


def check(root: Path) -> list[Violation]:
    violations: list[Violation] = []
    for path in iter_code_files(root):
        source = path.read_text(encoding="utf-8")
        violations.extend(comment_violations(path, source))
        violations.extend(ascii_violations(path, source))
    return violations


def main() -> int:
    violations = check(REPO_ROOT)
    for violation in violations:
        print(violation.render())
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
