"""Calendar utilities for the trend module.

Persian (Jalali) dates are kept for backward compatibility with historical
records (``*_jalali`` columns).  The active global pipeline uses the Gregorian
calendar for seasons, but every persisted row still carries a Jalali label so
that old data remains readable.

The module prefers ``jdatetime`` (a declared dependency) and falls back to a
self-contained conversion algorithm so that the pipeline never crashes when the
optional calendar library is unavailable.
"""

from __future__ import annotations

from datetime import datetime, timezone

try:  # pragma: no cover - exercised implicitly by every caller
    import jdatetime
except Exception:  # pragma: no cover - dependency is declared, fallback is safety net
    jdatetime = None


PERSIAN_MONTHS = [
    "Farvardin",
    "Ordibehesht",
    "Khordad",
    "Tir",
    "Mordad",
    "Shahrivar",
    "Mehr",
    "Aban",
    "Azar",
    "Dey",
    "Bahman",
    "Esfand",
]

# Season boundaries in the Persian calendar (month numbers are 1-based).
_PERSIAN_SEASON_BY_MONTH = {
    1: "spring", 2: "spring", 3: "spring",
    4: "summer", 5: "summer", 6: "summer",
    7: "autumn", 8: "autumn", 9: "autumn",
    10: "winter", 11: "winter", 12: "winter",
}


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Minimal Gregorian → Jalali conversion (no external dependency).

    Implements the well-known Khayyam/Jalaali algorithm used by jdatetime and
    jalaali-js.  Valid for the modern era covered by this project.
    """
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy - 1600
    gm2 = gm - 1
    gd2 = gd - 1
    g_day_no = 365 * gy2 + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
    g_day_no += g_d_m[gm2] + gd2
    if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1
    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053
    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461
    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365
    j_month_days = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
    jm = 1
    for days in j_month_days:
        if j_day_no < days:
            break
        j_day_no -= days
        jm += 1
    jd = j_day_no + 1
    return jy, jm, jd


def to_jalali(dt: datetime) -> tuple[int, int, int]:
    """Return ``(year, month, day)`` of a datetime in the Persian calendar."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if jdatetime is not None:
        j = jdatetime.datetime.fromgregorian(datetime=dt)
        return int(j.year), int(j.month), int(j.day)
    return _gregorian_to_jalali(dt.year, dt.month, dt.day)


def jalali_season(month: int) -> str:
    """Season for a Persian month number (1 = Farvardin)."""
    return _PERSIAN_SEASON_BY_MONTH.get(int(month), "winter")


def gregorian_season(month: int) -> str:
    """Season for a Gregorian month number.

    Northern-hemisphere meteorological seasons, matching the convention used by
    the trend aggregator and ``config/scoring.yaml`` (``calendar: gregorian``).
    """
    month = int(month)
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    return "winter"


def to_jalali_date_str(dt: datetime) -> str:
    year, month, day = to_jalali(dt)
    return f"{year:04d}-{month:02d}-{day:02d}"


def to_jalali_dict(dt: datetime) -> dict:
    """Structured Jalali representation used across the persistence layer."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    year, month, day = to_jalali(dt)
    return {
        "timestamp_utc": dt.astimezone(timezone.utc).isoformat(),
        "jalali_date": f"{year:04d}-{month:02d}-{day:02d}",
        "jalali_year": year,
        "jalali_month": month,
        "jalali_day": day,
        "jalali_month_name": PERSIAN_MONTHS[month - 1],
        "season": jalali_season(month),
        "gregorian_date": dt.date().isoformat(),
        "gregorian_month": dt.month,
        "gregorian_season": gregorian_season(dt.month),
    }
