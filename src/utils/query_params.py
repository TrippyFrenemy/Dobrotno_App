"""Utility functions for handling query parameters in FastAPI."""

from datetime import date
from typing import Optional


def optional_date(value: Optional[str] = None) -> Optional[date]:
    """
    Convert a query parameter to an optional date.

    Handles empty strings by converting them to None, which prevents
    FastAPI validation errors when date inputs are submitted as empty strings.

    Args:
        value: The query parameter value (can be None, empty string, or date string)

    Returns:
        None if value is None or empty string, otherwise parsed date

    Raises:
        ValueError: If the value is not a valid date format
    """
    if value is None or value == "":
        return None

    # If it's already a date object, return it
    if isinstance(value, date):
        return value

    # Parse the string as a date
    return date.fromisoformat(value)
