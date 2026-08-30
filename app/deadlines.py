from datetime import date, timedelta
from enum import Enum

# Cal. Code Civ. Proc. § 1167(a), as amended by AB 2347 (Kalra), Stats. 2024,
# ch. 512, operative 1 January 2025:
#
#   "the defendant's response shall be filed within 10 days, excluding
#    Saturdays and Sundays and other judicial holidays, after the complaint is
#    served upon the defendant."
#
# This was five days before that amendment, and this file said five until the
# statute was checked against the current text rather than against memory. A
# tool whose entire claim is that every legal statement carries a citation
# cannot afford to compute the most important date on the screen from a
# superseded version of the section it cites.
RESPONSE_COURT_DAYS = 10

# § 1167(b): "If service is completed by mail or in person through the
# Secretary of State's address confidentiality program ... the defendant shall
# have an additional five court days to file a response."
MAIL_EXTRA_COURT_DAYS = 5

# Cal. Code Civ. Proc. § 415.20(b): substituted service is deemed complete on
# the tenth day after the mailing. The response clock starts from that date,
# not from the day the papers were left.
SUBSTITUTED_COMPLETION_DAYS = 10


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
    """The last court day on which an Answer can be filed.

    Cal. Code Civ. Proc. § 1167 as amended by AB 2347: ten court days from
    completed service, plus five more where service was by mail.
    """
    if method == ServiceMethod.PERSONAL:
        return _add_court_days(served_on, RESPONSE_COURT_DAYS, holidays)
    if method == ServiceMethod.SUBSTITUTED:
        complete = served_on + timedelta(days=SUBSTITUTED_COMPLETION_DAYS)
        return _add_court_days(complete, RESPONSE_COURT_DAYS, holidays)
    if method == ServiceMethod.MAIL:
        return _add_court_days(
            served_on, RESPONSE_COURT_DAYS + MAIL_EXTRA_COURT_DAYS, holidays
        )
    raise ValueError(f"unknown service method: {method}")


def days_remaining(deadline: date, today: date) -> int:
    return (deadline - today).days
