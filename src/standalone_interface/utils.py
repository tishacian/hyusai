from datetime import datetime


def humanize_datetime(dt: datetime) -> str:
    """
    Converts a datetime object to a human-readable string.

    Example:
        2025-06-17T15:42:00Z -> "June 17, 2025 at 15:42 UTC"

    Parameters
    ----------
    dt : datetime
        The datetime object to format.

    Returns
    -------
    str
        A human-readable string representation.
    """
    if not dt:
        return "N/A"
    return dt.strftime("%B %d, %Y at %H:%M")
