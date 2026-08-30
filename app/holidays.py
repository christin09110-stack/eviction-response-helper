"""California judicial holidays, computed rather than fetched.

The deadline in this product is the number a tenant plans around, so the days
it skips have to be right. `compute_response_deadline` has always accepted a
set of holidays and nothing in production ever passed one, which meant every
real deadline was counted as though courts never close. That lands the date
too early, which is the safe direction to be wrong in, but it is still wrong,
and around Thanksgiving or Christmas it is wrong by several days.

This is deliberately a calculation and not an API call. The list is statutory:

  Cal. Code Civ. Proc. § 135 (as amended by AB 268, Stats. 2025 ch. 358,
  operative 1 January 2026) makes every full day designated a holiday by
  Gov. Code § 6700 a judicial holiday, **except** Lunar New Year, Diwali,
  Genocide Remembrance Day (April 24), Admission Day (September 9) and
  Columbus Day (the second Monday in October) -- and adds that "Every
  Saturday and the day after Thanksgiving Day are judicial holidays."

A network dependency on a page that could 404, rate-limit, or quietly change
shape is not something a court deadline should rest on.
"""

from datetime import date, timedelta

# Good Friday appears in § 6700 only as noon-to-3pm, which is not a full-day
# closure, so it is not a judicial holiday for counting purposes.


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth given weekday of a month. weekday: Monday=0."""
    day = date(year, month, 1)
    offset = (weekday - day.weekday()) % 7
    return day + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    day = date(year, month, 28)
    while (day + timedelta(days=7)).month == month:
        day += timedelta(days=7)
    return day - timedelta(days=(day.weekday() - weekday) % 7)


def judicial_holidays(year: int) -> frozenset[date]:
    """Full-day California judicial holidays in `year`.

    Saturdays and Sundays are judicial holidays too, but the court-day counter
    already excludes weekends by weekday, so listing 104 dates here would be
    noise. This returns only the dated holidays.
    """
    thanksgiving = _nth_weekday(year, 11, 3, 4)          # fourth Thursday
    days = {
        date(year, 1, 1),                                # New Year's Day
        _nth_weekday(year, 1, 0, 3),                     # Dr Martin Luther King, Jr. Day
        date(year, 2, 12),                               # Lincoln Day
        _nth_weekday(year, 2, 0, 3),                     # third Monday in February
        date(year, 3, 31),                               # Farmworkers Day
        _last_weekday(year, 5, 0),                       # Memorial Day
        date(year, 6, 19),                               # Juneteenth
        date(year, 7, 4),                                # Independence Day
        _nth_weekday(year, 9, 0, 1),                     # Labor Day
        _nth_weekday(year, 9, 4, 4),                     # Native American Day
        date(year, 11, 11),                              # Veterans Day
        thanksgiving,
        thanksgiving + timedelta(days=1),                # the day after, per § 135
        date(year, 12, 25),                              # Christmas Day
    }
    return frozenset(days)


def holidays_around(day: date) -> frozenset[date]:
    """Holidays for the year of `day` and the one after it.

    A response window opened in late December runs into January, so counting
    from a single year's set would silently skip New Year's Day.
    """
    return judicial_holidays(day.year) | judicial_holidays(day.year + 1)
