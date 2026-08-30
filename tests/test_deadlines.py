from datetime import date

import pytest

from app.deadlines import ServiceMethod, compute_response_deadline, days_remaining


def test_personal_service_is_ten_court_days_from_a_monday():
    # CCP 1167(a) as amended by AB 2347: ten court days, not five.
    # Mon 3 Aug served -> 4,5,6,7 / 10,11,12,13,14 / 17 = Mon 17 Aug
    assert compute_response_deadline(date(2026, 8, 3), ServiceMethod.PERSONAL) == date(2026, 8, 17)


def test_weekends_are_excluded():
    # Thu 6 Aug served -> 7 / 10-14 / 17-20 = Thu 20 Aug
    assert compute_response_deadline(date(2026, 8, 6), ServiceMethod.PERSONAL) == date(2026, 8, 20)


def test_holidays_are_excluded():
    holidays = frozenset({date(2026, 8, 7)})
    # Thu 6 Aug served, Fri 7 is a holiday -> 10-14 / 17-21 = Fri 21 Aug
    assert compute_response_deadline(
        date(2026, 8, 6), ServiceMethod.PERSONAL, holidays
    ) == date(2026, 8, 21)


def test_substituted_service_completes_ten_days_after_mailing():
    # CCP 415.20(b): service complete on the tenth day after mailing, so
    # 3 Aug -> complete 13 Aug, then ten court days = Thu 27 Aug.
    assert compute_response_deadline(
        date(2026, 8, 3), ServiceMethod.SUBSTITUTED
    ) == date(2026, 8, 27)


def test_mail_service_adds_five_court_days_to_the_ten():
    # CCP 1167(b) gives "an additional five court days" -- court days, added to
    # the ten, not five calendar days bolted onto the front. 15 court days from
    # Mon 3 Aug = Mon 24 Aug.
    assert compute_response_deadline(date(2026, 8, 3), ServiceMethod.MAIL) == date(2026, 8, 24)


def test_service_on_a_saturday_still_counts_forward():
    # Sat 8 Aug served -> 10-14 / 17-21 = Fri 21 Aug
    assert compute_response_deadline(date(2026, 8, 8), ServiceMethod.PERSONAL) == date(2026, 8, 21)


def test_days_remaining_is_positive_before_the_deadline():
    assert days_remaining(date(2026, 8, 10), today=date(2026, 8, 7)) == 3


def test_days_remaining_is_zero_on_the_deadline():
    assert days_remaining(date(2026, 8, 10), today=date(2026, 8, 10)) == 0


def test_days_remaining_is_negative_after_the_deadline():
    assert days_remaining(date(2026, 8, 10), today=date(2026, 8, 12)) == -2


def test_rejects_an_unknown_service_method():
    with pytest.raises(ValueError, match="unknown service method"):
        compute_response_deadline(date(2026, 8, 3), "carrier pigeon")


# --- Edge cases the ten tests above do not cover ---


def test_a_holiday_that_falls_on_a_weekend_changes_nothing():
    # Sat 8 Aug is already excluded as a weekend; declaring it a holiday too
    # must not shift the deadline versus the plain weekend case.
    holidays = frozenset({date(2026, 8, 8)})
    assert compute_response_deadline(
        date(2026, 8, 6), ServiceMethod.PERSONAL, holidays
    ) == date(2026, 8, 20)


def test_the_deadline_itself_never_lands_on_a_holiday():
    # Without a holiday, Thu 6 Aug -> Thu 13 Aug (per test_weekends_are_excluded).
    # Declaring that would-be deadline day a holiday must push the deadline to
    # the next court day, not return the holiday itself.
    holidays = frozenset({date(2026, 8, 20)})
    deadline = compute_response_deadline(date(2026, 8, 6), ServiceMethod.PERSONAL, holidays)
    assert deadline == date(2026, 8, 21)
    assert deadline not in holidays


def test_service_on_a_holiday_weekday_still_counts_forward_from_the_next_day():
    # Serving on a holiday that happens to be a weekday does not itself get
    # counted or skipped specially -- counting simply begins the next day, the
    # same as it would for any other served_on date.
    holidays = frozenset({date(2026, 8, 7)})  # Fri 7 Aug is a weekday holiday
    assert compute_response_deadline(
        date(2026, 8, 7), ServiceMethod.PERSONAL, holidays
    ) == date(2026, 8, 21)


def test_a_service_date_in_the_past_still_computes_a_deadline():
    # The function is pure and takes no notion of "today" -- a stale served_on
    # is not rejected here. days_remaining is the layer that tells the caller
    # the window has closed.
    deadline = compute_response_deadline(date(2020, 1, 1), ServiceMethod.PERSONAL)
    assert deadline == date(2020, 1, 15)


def test_court_day_counting_crosses_a_leap_day_correctly():
    # Wed 25 Feb 2032 (a leap year) served -> 26,27 (Sat 28/Sun 29 skipped,
    # including the leap day itself), 1-5 Mar, 8,9,10 Mar = Wed 10 Mar 2032.
    assert compute_response_deadline(
        date(2032, 2, 25), ServiceMethod.PERSONAL
    ) == date(2032, 3, 10)
