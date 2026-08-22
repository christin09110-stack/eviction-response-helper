from datetime import date, timedelta
from enum import Enum

RESPONSE_COURT_DAYS = 5  # Cal. Code Civ. Proc. § 1167
SUBSTITUTED_COMPLETION_DAYS = 10
MAIL_EXTENSION_DAYS = 5


class ServiceMethod(str, Enum):
    PERSONAL = "personal"
    SUBSTITUTED = "substituted"
    MAIL = "mail"


def _is_court_day(day: date, holidays: frozenset[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def _add_court_days(start: date, count: int, holidays: frozenset[date]) -> date:
    current, remaining = start, count
    while remaining > 0:
        current += timedelta(days=1)
        if _is_court_day(current, holidays):
            remaining -= 1
    return current


def compute_response_deadline(
    served_on: date, method: ServiceMethod, holidays: frozenset[date] = frozenset()
) -> date:
    """Cal. Code Civ. Proc. § 1167: five court days from completed service."""
    if method == ServiceMethod.PERSONAL:
        effective = served_on
    elif method == ServiceMethod.SUBSTITUTED:
        effective = served_on + timedelta(days=SUBSTITUTED_COMPLETION_DAYS)
    elif method == ServiceMethod.MAIL:
        effective = served_on + timedelta(days=MAIL_EXTENSION_DAYS)
    else:
        raise ValueError(f"unknown service method: {method}")
    return _add_court_days(effective, RESPONSE_COURT_DAYS, holidays)


def days_remaining(deadline: date, today: date) -> int:
    return (deadline - today).days
