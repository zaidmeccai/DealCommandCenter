"""Calendar parser - extracts meeting entries from pasted calendar text."""

import re
from dataclasses import dataclass


@dataclass
class CalendarEntry:
    time: str
    title: str
    raw: str


def parse_calendar_input(text: str) -> list[CalendarEntry]:
    """Parse pasted calendar text into structured entries.

    Handles common calendar paste formats:
    - "10:00 AM - Meeting with CarMax"
    - "10:00-11:00 CarMax Technical Review"
    - "10a - CarMax sync"
    - "2:30 PM: GoodLeap follow-up"
    - "14:00 GoodLeap call"
    - Bullet/dash prefixed variants of the above
    """
    entries: list[CalendarEntry] = []

    # Time patterns to try
    time_pattern = re.compile(
        r"^[\s\-\*\u2022]*"  # optional leading whitespace, bullets, dashes
        r"(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM|a|p)?)"  # time
        r"[\s\-:~to]*"  # separator
        r"(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM|a|p)?)?"  # optional end time
        r"[\s\-:~]*"  # separator
        r"(.+)"  # title
    )

    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        match = time_pattern.match(line)
        if match:
            time_str = match.group(1).strip()
            title = match.group(2).strip()
            # Clean up title - remove trailing whitespace, common artifacts
            title = re.sub(r"\s+", " ", title).strip()
            entries.append(CalendarEntry(time=time_str, title=title, raw=line))
        else:
            # No time found - treat whole line as a meeting title
            clean = re.sub(r"^[\s\-\*\u2022]+", "", line).strip()
            if clean and len(clean) > 3:
                entries.append(CalendarEntry(time="", title=clean, raw=line))

    return entries


def match_calendar_to_accounts(
    entries: list[CalendarEntry],
    account_names: list[str],
) -> list[tuple[str, str | None]]:
    """Match calendar entries to account names.

    Returns list of (calendar_entry_display, matched_account_name_or_None).
    """
    results: list[tuple[str, str | None]] = []

    for entry in entries:
        display = f"{entry.time + ' - ' if entry.time else ''}{entry.title}"
        matched_account = None
        entry_lower = entry.title.lower()

        for account in account_names:
            account_lower = account.lower()
            # Check if any significant word of the account name appears in the calendar entry
            words = [w for w in account_lower.split() if len(w) >= 3]

            if account_lower in entry_lower:
                matched_account = account
                break
            if words and all(w in entry_lower for w in words):
                matched_account = account
                break
            # Also check without common suffixes
            for suffix in [" inc", " llc", " corp", " ltd", " co"]:
                clean = account_lower.replace(suffix, "").strip()
                if clean and clean in entry_lower:
                    matched_account = account
                    break
            if matched_account:
                break

        results.append((display, matched_account))

    return results
