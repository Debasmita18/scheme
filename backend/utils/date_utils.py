"""
Date and calendar utilities for the MGNREGA Verification system.

Handles MGNREGA financial-year logic (April -- March), satellite-pass
date ranges, Indian-holiday-aware working-day calculations, and
detection of suspicious attendance-date patterns.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Sequence

# ===========================================================================
# Indian national / gazetted holidays (fixed-date approximations).
#
# Holidays whose dates vary by year (e.g. Diwali, Eid, Holi) are included
# with their most common Gregorian dates; the ``get_indian_holidays``
# function should be refreshed annually with the official gazette list.
# ===========================================================================

_FIXED_HOLIDAYS_MD: list[tuple[int, int, str]] = [
    (1, 26, "Republic Day"),
    (3, 8, "Maha Shivaratri"),             # approximate
    (3, 25, "Holi"),                         # approximate
    (4, 14, "Dr Ambedkar Jayanti"),
    (4, 17, "Ram Navami"),                   # approximate
    (4, 21, "Mahavir Jayanti"),              # approximate
    (5, 1, "May Day"),
    (5, 23, "Buddha Purnima"),               # approximate
    (6, 17, "Eid ul-Fitr"),                  # approximate, shifts yearly
    (7, 17, "Muharram"),                     # approximate
    (8, 15, "Independence Day"),
    (8, 26, "Janmashtami"),                  # approximate
    (9, 16, "Milad-un-Nabi"),                # approximate
    (10, 2, "Gandhi Jayanti"),
    (10, 12, "Dussehra"),                    # approximate
    (10, 24, "Dussehra (additional)"),       # approximate
    (11, 1, "Diwali"),                       # approximate
    (11, 15, "Guru Nanak Jayanti"),          # approximate
    (12, 25, "Christmas"),
]


def get_indian_holidays(year: int) -> dict[date, str]:
    """Return a mapping of ``date -> holiday_name`` for a given calendar year.

    Uses the fixed-date approximation table above.  For production use,
    this should be supplemented with the official gazette notification
    published by the Department of Personnel & Training each year.

    Args:
        year: Calendar year (e.g. 2025).

    Returns:
        Dict mapping each holiday ``date`` to its name.
    """
    holidays: dict[date, str] = {}
    for month, day, name in _FIXED_HOLIDAYS_MD:
        try:
            holidays[date(year, month, day)] = name
        except ValueError:
            # Handles Feb 29 in non-leap years, etc.
            pass
    return holidays


# ===========================================================================
# MGNREGA financial year (April -- March)
# ===========================================================================

def financial_year_for_date(d: date) -> str:
    """Return the MGNREGA financial year string for a given date.

    The MGNREGA financial year runs from 1 April to 31 March.

    Args:
        d: Any calendar date.

    Returns:
        String in the format ``"YYYY-YYYY"`` (e.g. ``"2024-2025"``).

    Examples:
        >>> financial_year_for_date(date(2025, 1, 15))
        '2024-2025'
        >>> financial_year_for_date(date(2025, 4, 1))
        '2025-2026'
    """
    if d.month >= 4:
        return f"{d.year}-{d.year + 1}"
    return f"{d.year - 1}-{d.year}"


def financial_year_date_range(fy_str: str) -> tuple[date, date]:
    """Return the start and end dates of a financial year string.

    Args:
        fy_str: Financial year in ``"YYYY-YYYY"`` format (e.g. ``"2024-2025"``).

    Returns:
        Tuple ``(start_date, end_date)`` where start is 1 April of the
        first year and end is 31 March of the second year.

    Raises:
        ValueError: If the string does not conform to the expected format.
    """
    parts = fy_str.split("-")
    if len(parts) != 2:
        raise ValueError(f"Expected format 'YYYY-YYYY', got '{fy_str}'")

    start_year = int(parts[0])
    end_year = int(parts[1])

    if end_year != start_year + 1:
        raise ValueError(
            f"End year must be start year + 1; got {start_year}-{end_year}"
        )

    return date(start_year, 4, 1), date(end_year, 3, 31)


def current_financial_year() -> str:
    """Return the financial year string for today's date."""
    return financial_year_for_date(date.today())


# ===========================================================================
# Satellite-pass date ranges
# ===========================================================================

def satellite_pass_date_range(
    work_start: date,
    work_end: date,
    *,
    before_buffer_days: int = 30,
    after_buffer_days: int = 30,
    revisit_interval_days: int = 5,
) -> list[tuple[date, date]]:
    """Generate date windows suitable for querying satellite imagery.

    Creates a *before* window (prior to work start) and an *after* window
    (following work completion) that can be used to search for
    cloud-free Sentinel-2 scenes.

    Additionally, intermediate windows at the ``revisit_interval_days``
    cadence are generated for the work duration itself so that
    progress can be tracked.

    Args:
        work_start: Date the work commenced.
        work_end: Date the work was completed (or expected completion).
        before_buffer_days: Days before ``work_start`` to search for
            baseline imagery.
        after_buffer_days: Days after ``work_end`` to search for
            post-completion imagery.
        revisit_interval_days: Interval between intermediate passes
            (default 5 days, matching Sentinel-2 revisit period).

    Returns:
        List of ``(window_start, window_end)`` tuples.
    """
    windows: list[tuple[date, date]] = []

    # Before window
    before_start = work_start - timedelta(days=before_buffer_days)
    windows.append((before_start, work_start - timedelta(days=1)))

    # Intermediate windows during work execution
    cursor = work_start
    while cursor <= work_end:
        window_end = min(cursor + timedelta(days=revisit_interval_days - 1), work_end)
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)

    # After window
    after_end = work_end + timedelta(days=after_buffer_days)
    windows.append((work_end + timedelta(days=1), after_end))

    return windows


# ===========================================================================
# Working days calculator
# ===========================================================================

def count_working_days(
    start: date,
    end: date,
    *,
    exclude_sundays: bool = True,
    exclude_second_saturdays: bool = True,
    exclude_fourth_saturdays: bool = True,
    custom_holidays: Optional[dict[date, str]] = None,
) -> int:
    """Count the number of working days in a date range, excluding
    Sundays, specified Saturdays, and Indian holidays.

    MGNREGA works typically exclude Sundays and the 2nd / 4th Saturdays
    as non-working days, aligned with central government office rules.

    Args:
        start: First date of the range (inclusive).
        end: Last date of the range (inclusive).
        exclude_sundays: Exclude all Sundays.
        exclude_second_saturdays: Exclude the 2nd Saturday of each month.
        exclude_fourth_saturdays: Exclude the 4th Saturday of each month.
        custom_holidays: Optional override holiday mapping. If ``None``,
            holidays for the relevant years are generated automatically.

    Returns:
        Number of working days in the range.

    Raises:
        ValueError: If ``start`` is after ``end``.
    """
    if start > end:
        raise ValueError(f"start ({start}) is after end ({end})")

    # Build holiday set
    if custom_holidays is None:
        years = set(range(start.year, end.year + 1))
        all_holidays: dict[date, str] = {}
        for yr in years:
            all_holidays.update(get_indian_holidays(yr))
    else:
        all_holidays = custom_holidays

    # Pre-compute 2nd and 4th Saturday dates for each month in range
    non_working_saturdays: set[date] = set()
    if exclude_second_saturdays or exclude_fourth_saturdays:
        current_month = date(start.year, start.month, 1)
        end_month = date(end.year, end.month, 1)
        while current_month <= end_month:
            sats = _saturdays_of_month(current_month.year, current_month.month)
            if exclude_second_saturdays and len(sats) >= 2:
                non_working_saturdays.add(sats[1])
            if exclude_fourth_saturdays and len(sats) >= 4:
                non_working_saturdays.add(sats[3])
            # Advance to next month
            if current_month.month == 12:
                current_month = date(current_month.year + 1, 1, 1)
            else:
                current_month = date(current_month.year, current_month.month + 1, 1)

    working_days = 0
    cursor = start
    while cursor <= end:
        is_working = True

        # Sunday check
        if exclude_sundays and cursor.weekday() == 6:
            is_working = False

        # 2nd / 4th Saturday check
        if is_working and cursor.weekday() == 5 and cursor in non_working_saturdays:
            is_working = False

        # Holiday check
        if is_working and cursor in all_holidays:
            is_working = False

        if is_working:
            working_days += 1

        cursor += timedelta(days=1)

    return working_days


def get_non_working_dates(
    start: date,
    end: date,
    *,
    custom_holidays: Optional[dict[date, str]] = None,
) -> dict[date, str]:
    """Return all non-working dates in a range with reasons.

    Args:
        start: First date (inclusive).
        end: Last date (inclusive).
        custom_holidays: Optional holiday override.

    Returns:
        Dict mapping each non-working date to its reason string
        (e.g. ``"Sunday"``, ``"2nd Saturday"``, ``"Republic Day"``).
    """
    if start > end:
        raise ValueError(f"start ({start}) is after end ({end})")

    if custom_holidays is None:
        years = set(range(start.year, end.year + 1))
        all_holidays: dict[date, str] = {}
        for yr in years:
            all_holidays.update(get_indian_holidays(yr))
    else:
        all_holidays = custom_holidays

    # Compute non-working Saturdays
    nw_sats: dict[date, str] = {}
    current_month = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)
    while current_month <= end_month:
        sats = _saturdays_of_month(current_month.year, current_month.month)
        if len(sats) >= 2:
            nw_sats[sats[1]] = "2nd Saturday"
        if len(sats) >= 4:
            nw_sats[sats[3]] = "4th Saturday"
        if current_month.month == 12:
            current_month = date(current_month.year + 1, 1, 1)
        else:
            current_month = date(current_month.year, current_month.month + 1, 1)

    result: dict[date, str] = {}
    cursor = start
    while cursor <= end:
        if cursor.weekday() == 6:
            result[cursor] = "Sunday"
        elif cursor in nw_sats:
            result[cursor] = nw_sats[cursor]
        elif cursor in all_holidays:
            result[cursor] = all_holidays[cursor]
        cursor += timedelta(days=1)

    return result


# ===========================================================================
# Suspicious date-pattern detection
# ===========================================================================

class SuspiciousDateFinding:
    """A single suspicious-date finding with details."""

    __slots__ = ("finding_type", "dates", "description", "severity")

    def __init__(
        self,
        finding_type: str,
        dates: list[date],
        description: str,
        severity: str = "medium",
    ) -> None:
        self.finding_type = finding_type
        self.dates = dates
        self.description = description
        self.severity = severity

    def to_dict(self) -> dict:
        return {
            "finding_type": self.finding_type,
            "dates": [d.isoformat() for d in self.dates],
            "description": self.description,
            "severity": self.severity,
        }

    def __repr__(self) -> str:
        return (
            f"SuspiciousDateFinding(type={self.finding_type!r}, "
            f"dates={len(self.dates)}, severity={self.severity!r})"
        )


def detect_suspicious_date_patterns(
    attendance_dates: Sequence[date],
    work_start: Optional[date] = None,
    work_end: Optional[date] = None,
    *,
    custom_holidays: Optional[dict[date, str]] = None,
    max_consecutive_days: int = 14,
) -> list[SuspiciousDateFinding]:
    """Analyse a list of attendance dates for patterns that indicate
    potential fraud in MGNREGA muster rolls.

    Checks performed:
    1. **Weekend attendance** -- work recorded on Sundays.
    2. **Holiday attendance** -- work recorded on gazetted holidays.
    3. **Non-working Saturday attendance** -- work on 2nd/4th Saturdays.
    4. **Impossible streaks** -- continuous attendance exceeding
       ``max_consecutive_days`` without a break.
    5. **Future-dated attendance** -- dates in the future.
    6. **Out-of-range attendance** -- dates outside the work's start/end
       window (if provided).

    Args:
        attendance_dates: Sorted list of dates a worker was marked present.
        work_start: Optional start date of the work.
        work_end: Optional end date of the work.
        custom_holidays: Optional holiday mapping override.
        max_consecutive_days: Threshold for flagging impossible attendance
            streaks (default 14).

    Returns:
        List of :class:`SuspiciousDateFinding` objects describing each
        anomaly detected. Empty list if no issues are found.
    """
    if not attendance_dates:
        return []

    sorted_dates = sorted(set(attendance_dates))
    findings: list[SuspiciousDateFinding] = []

    # Build holiday / non-working-day lookup
    if sorted_dates:
        nw = get_non_working_dates(
            sorted_dates[0],
            sorted_dates[-1],
            custom_holidays=custom_holidays,
        )
    else:
        nw = {}

    # 1 & 2 & 3 -- attendance on non-working days
    sunday_dates: list[date] = []
    holiday_dates: list[date] = []
    nw_saturday_dates: list[date] = []

    for d in sorted_dates:
        if d in nw:
            reason = nw[d]
            if reason == "Sunday":
                sunday_dates.append(d)
            elif "Saturday" in reason:
                nw_saturday_dates.append(d)
            else:
                holiday_dates.append(d)

    if sunday_dates:
        findings.append(SuspiciousDateFinding(
            finding_type="weekend_attendance",
            dates=sunday_dates,
            description=(
                f"Attendance recorded on {len(sunday_dates)} Sunday(s). "
                "MGNREGA works do not operate on Sundays."
            ),
            severity="high",
        ))

    if holiday_dates:
        holiday_names = ", ".join(
            f"{d.isoformat()} ({nw.get(d, 'holiday')})" for d in holiday_dates[:5]
        )
        findings.append(SuspiciousDateFinding(
            finding_type="holiday_attendance",
            dates=holiday_dates,
            description=(
                f"Attendance recorded on {len(holiday_dates)} gazetted holiday(s): "
                f"{holiday_names}."
            ),
            severity="high",
        ))

    if nw_saturday_dates:
        findings.append(SuspiciousDateFinding(
            finding_type="non_working_saturday_attendance",
            dates=nw_saturday_dates,
            description=(
                f"Attendance on {len(nw_saturday_dates)} non-working Saturday(s) "
                "(2nd/4th Saturday of the month)."
            ),
            severity="medium",
        ))

    # 4 -- impossible consecutive streaks
    if len(sorted_dates) >= 2:
        streak_start = sorted_dates[0]
        streak_dates: list[date] = [streak_start]

        for i in range(1, len(sorted_dates)):
            if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
                streak_dates.append(sorted_dates[i])
            else:
                if len(streak_dates) > max_consecutive_days:
                    findings.append(SuspiciousDateFinding(
                        finding_type="impossible_attendance_streak",
                        dates=list(streak_dates),
                        description=(
                            f"Continuous attendance for {len(streak_dates)} consecutive "
                            f"days ({streak_dates[0].isoformat()} to "
                            f"{streak_dates[-1].isoformat()}) without a single break. "
                            f"Threshold is {max_consecutive_days} days."
                        ),
                        severity="critical",
                    ))
                streak_dates = [sorted_dates[i]]

        # Check the final streak
        if len(streak_dates) > max_consecutive_days:
            findings.append(SuspiciousDateFinding(
                finding_type="impossible_attendance_streak",
                dates=list(streak_dates),
                description=(
                    f"Continuous attendance for {len(streak_dates)} consecutive "
                    f"days ({streak_dates[0].isoformat()} to "
                    f"{streak_dates[-1].isoformat()}) without a single break."
                ),
                severity="critical",
            ))

    # 5 -- future-dated attendance
    today = date.today()
    future_dates = [d for d in sorted_dates if d > today]
    if future_dates:
        findings.append(SuspiciousDateFinding(
            finding_type="future_dated_attendance",
            dates=future_dates,
            description=(
                f"{len(future_dates)} attendance date(s) are in the future "
                f"(earliest: {future_dates[0].isoformat()}). "
                "This indicates pre-filled or fabricated records."
            ),
            severity="critical",
        ))

    # 6 -- out-of-range attendance
    if work_start or work_end:
        out_of_range: list[date] = []
        for d in sorted_dates:
            if work_start and d < work_start:
                out_of_range.append(d)
            elif work_end and d > work_end:
                out_of_range.append(d)

        if out_of_range:
            findings.append(SuspiciousDateFinding(
                finding_type="out_of_range_attendance",
                dates=out_of_range,
                description=(
                    f"{len(out_of_range)} attendance date(s) fall outside the "
                    f"work period ({work_start} to {work_end})."
                ),
                severity="high",
            ))

    return findings


# ===========================================================================
# Internal helpers
# ===========================================================================

def _saturdays_of_month(year: int, month: int) -> list[date]:
    """Return an ordered list of all Saturday dates in a given month.

    Args:
        year: Calendar year.
        month: Calendar month (1-12).

    Returns:
        List of ``date`` objects for each Saturday in the month.
    """
    saturdays: list[date] = []
    d = date(year, month, 1)

    # Advance to first Saturday
    while d.weekday() != 5:
        d += timedelta(days=1)

    while d.month == month:
        saturdays.append(d)
        d += timedelta(days=7)

    return saturdays
