from datetime import date

from app.deadlines import ServiceMethod, compute_response_deadline
from app.holidays import holidays_around, judicial_holidays


def test_the_fixed_date_holidays_are_present():
    h = judicial_holidays(2026)
    for day in (date(2026, 1, 1), date(2026, 2, 12), date(2026, 3, 31),
                date(2026, 6, 19), date(2026, 7, 4), date(2026, 11, 11),
                date(2026, 12, 25)):
        assert day in h, day


def test_the_floating_holidays_land_on_the_right_weekday():
    h = judicial_holidays(2026)
    assert date(2026, 1, 19) in h      # third Monday in January
    assert date(2026, 2, 16) in h      # third Monday in February
    assert date(2026, 5, 25) in h      # last Monday in May
    assert date(2026, 9, 7) in h       # first Monday in September
    assert date(2026, 9, 25) in h      # fourth Friday in September
    assert date(2026, 11, 26) in h     # fourth Thursday in November


def test_the_day_after_thanksgiving_is_a_judicial_holiday():
    """§ 135 adds it explicitly; § 6700 does not list it."""
    assert date(2026, 11, 27) in judicial_holidays(2026)


def test_the_sections_135_exclusions_are_not_holidays():
    """§ 6700 lists these; § 135 excludes them from judicial holidays."""
    h = judicial_holidays(2026)
    assert date(2026, 9, 9) not in h        # Admission Day
    assert date(2026, 4, 24) not in h       # Genocide Remembrance Day
    assert date(2026, 10, 12) not in h      # Columbus Day, second Monday


def test_a_window_opened_in_december_still_sees_new_year():
    """Counting from one year's set would skip 1 January silently."""
    h = holidays_around(date(2026, 12, 22))
    assert date(2027, 1, 1) in h


def test_thanksgiving_actually_moves_the_deadline():
    """The regression this module exists for.

    Served Mon 16 Nov 2026, personal service, ten court days. Thanksgiving
    (26 Nov) and the day after (27 Nov) are judicial holidays, so the deadline
    is two court days later than a naive weekday count would give.
    """
    served = date(2026, 11, 16)
    naive = compute_response_deadline(served, ServiceMethod.PERSONAL)
    real = compute_response_deadline(served, ServiceMethod.PERSONAL, holidays_around(served))
    assert naive == date(2026, 11, 30)
    assert real == date(2026, 12, 2)
    assert real > naive
