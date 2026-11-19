"""Validate the publisher's UTC schedule and resolve the message at a given instant."""

from datetime import datetime, timezone


def message_text(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 120
        or not value.isprintable()
    ):
        raise ValueError("Use 1–120 printable characters for each message.")
    return value.strip()


def message_timestamp(value):
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value:
            return int(parsed.timestamp())
    except (TypeError, ValueError, OverflowError):
        pass
    raise ValueError("Use UTC times in YYYY-MM-DDTHH:MM:SSZ format.")


def parse_message_feed(record):
    if not isinstance(record, dict):
        raise ValueError("Invalid message feed.")
    fallback = message_text(record.get("message"))
    rows = record.get("schedule", [])
    if not isinstance(rows, list) or len(rows) > 64:
        raise ValueError("Queue up to 64 announcements.")
    windows = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid announcement.")
        start, end = (
            message_timestamp(row.get("start")),
            message_timestamp(row.get("end")),
        )
        if end <= start:
            raise ValueError("Expiration must follow the start time.")
        windows.append((start, end, message_text(row.get("message"))))
    windows.sort()
    if any(a[1] > b[0] for a, b in zip(windows, windows[1:])):
        raise ValueError("Announcement times overlap.")
    return fallback, windows


def scheduled_message(feed, now):
    fallback, windows = feed
    for start, end, message in windows:
        if now < start:
            return fallback, start
        if now < end:
            return message, end
    return fallback, float("inf")
