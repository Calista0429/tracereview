from datetime import UTC, datetime


def now_iso() -> str:
    """Server-generated UTC timestamp, e.g. ``2026-11-02T09:30:00.123Z``."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
