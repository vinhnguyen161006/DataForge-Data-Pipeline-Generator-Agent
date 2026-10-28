"""Validate portable CSV names shared by batch declarations and uploads."""

import unicodedata


def csv_filename(value: str) -> str:
    if (
        not value
        or value != value.strip()
        or len(value) > 255
        or unicodedata.normalize("NFC", value) != value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
        or any(char in '<>:"/\\|?*' for char in value)
        or not value.lower().endswith(".csv")
        or value.startswith(".")
    ):
        raise ValueError(
            "Expected a portable CSV filename without directories or surrounding spaces"
        )
    stem = value.split(".", 1)[0].upper()
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if stem in reserved:
        raise ValueError("Reserved device names cannot be used as filenames")
    return value


def required_filenames(values: list[str]) -> list[str]:
    if not values:
        raise ValueError("At least one required CSV filename must be declared")
    names = [csv_filename(value) for value in values]
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError(
            "Required filenames must be unique, including case-insensitive comparisons"
        )
    return sorted(names)
