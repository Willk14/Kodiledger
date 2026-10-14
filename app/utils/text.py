"""Helpers for parsing simple text-based configuration values."""


def split_csv_values(value: str) -> list[str]:
    """Split a comma-separated setting, trimming whitespace and blanks."""
    return [part.strip() for part in value.split(",") if part.strip()]
