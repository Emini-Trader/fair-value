"""Unit tests for the futures expiration calendar."""

import datetime as dt

import pytest

from fairvalue import calendar as cal


@pytest.mark.parametrize(
    "year,month,expected",
    [
        (2024, 3, dt.date(2024, 3, 15)),
        (2024, 6, dt.date(2024, 6, 21)),
        (2024, 9, dt.date(2024, 9, 20)),
        (2024, 12, dt.date(2024, 12, 20)),
        (2023, 12, dt.date(2023, 12, 15)),
        (2025, 6, dt.date(2025, 6, 20)),
        (2025, 3, dt.date(2025, 3, 21)),
    ],
)
def test_third_friday(year, month, expected):
    assert cal.third_friday(year, month) == expected


def test_is_quarterly_expiration():
    assert cal.is_quarterly_expiration(dt.date(2024, 6, 21))
    assert not cal.is_quarterly_expiration(dt.date(2024, 6, 20))  # Thursday
    assert not cal.is_quarterly_expiration(dt.date(2024, 5, 17))  # 3rd Fri, wrong month


def test_next_quarterly_expiration_mid_quarter():
    assert cal.next_quarterly_expiration(dt.date(2024, 4, 1)) == dt.date(2024, 6, 21)


def test_next_quarterly_expiration_on_expiry_day():
    day = dt.date(2024, 6, 21)
    assert cal.next_quarterly_expiration(day, on_or_after=True) == day
    assert cal.next_quarterly_expiration(day, on_or_after=False) == dt.date(2024, 9, 20)


def test_next_quarterly_expiration_rolls_into_next_year():
    assert cal.next_quarterly_expiration(dt.date(2024, 12, 21)) == dt.date(2025, 3, 21)


def test_days_to_expiry():
    assert cal.days_to_expiry(dt.date(2024, 4, 1), dt.date(2024, 6, 21)) == 81
    assert cal.days_to_expiry(dt.date(2024, 6, 21), dt.date(2024, 6, 21)) == 0


def test_contract_code():
    assert cal.contract_code(dt.date(2024, 6, 21)) == "ESM24"
    assert cal.contract_code(dt.date(2024, 12, 20), root="SP") == "SPZ24"
    assert cal.contract_code(dt.date(2025, 3, 21)) == "ESH25"


@pytest.mark.parametrize(
    "year,expected",
    [
        (2024, dt.date(2024, 3, 29)),
        (2025, dt.date(2025, 4, 18)),
        (2026, dt.date(2026, 4, 3)),
    ],
)
def test_good_friday(year, expected):
    assert cal.good_friday(year) == expected


@pytest.mark.parametrize(
    "year,expected",
    [
        (2026, dt.date(2026, 6, 19)),  # Friday -> itself
        (2022, dt.date(2022, 6, 20)),  # Sunday -> observed Monday
        (2027, dt.date(2027, 6, 18)),  # Saturday -> observed Friday
    ],
)
def test_juneteenth_observed(year, expected):
    assert cal.juneteenth_observed(year) == expected


def test_settlement_rolls_back_off_juneteenth():
    # 3rd Friday of June 2026 is June 19 = Juneteenth -> settle Thursday June 18.
    assert cal.third_friday(2026, 6) == dt.date(2026, 6, 19)
    assert cal.settlement_date(2026, 6) == dt.date(2026, 6, 18)


def test_settlement_unaffected_when_friday_is_open():
    assert cal.settlement_date(2026, 9) == dt.date(2026, 9, 18)  # 3rd Friday, open
    assert cal.settlement_date(2024, 6) == dt.date(2024, 6, 21)  # Juneteenth was Wed


def test_next_quarterly_settlement_uses_adjusted_dates():
    assert cal.next_quarterly_settlement(dt.date(2026, 5, 29)) == dt.date(2026, 6, 18)
    assert (
        cal.next_quarterly_settlement(dt.date(2026, 6, 18), on_or_after=False)
        == dt.date(2026, 9, 18)
    )


@pytest.mark.parametrize(
    "year,month,expected",
    [
        (2025, 3, dt.date(2025, 3, 17)),   # 3rd Fri 03-21 -> Monday 03-17
        (2025, 6, dt.date(2025, 6, 16)),   # 3rd Fri 06-20 -> Monday 06-16
        (2025, 9, dt.date(2025, 9, 15)),   # 3rd Fri 09-19 -> Monday 09-15
        (2026, 6, dt.date(2026, 6, 15)),   # 3rd Fri 06-19 -> Monday 06-15
    ],
)
def test_roll_monday(year, month, expected):
    assert cal.roll_monday(year, month) == expected


def test_front_settlement_before_roll_is_nearest_quarterly():
    assert cal.front_settlement(dt.date(2026, 2, 13)) == dt.date(2026, 3, 20)
    # the Friday before roll Monday is still the same front
    assert cal.front_settlement(dt.date(2026, 3, 13)) == dt.date(2026, 3, 20)


def test_front_settlement_rolls_on_monday_of_expiration_week():
    # indexarb's verified rolls: from the Monday of expiry week the front advances
    assert cal.front_settlement(dt.date(2025, 3, 19)) == dt.date(2025, 6, 20)   # MAR->JUN
    assert cal.front_settlement(dt.date(2025, 6, 20)) == dt.date(2025, 9, 19)   # JUN->SEP
    assert cal.front_settlement(dt.date(2025, 9, 15)) == dt.date(2025, 12, 19)  # the Monday
    # Juneteenth quarter: rolls on Monday 06-15 even though settlement is Thu 06-18
    assert cal.front_settlement(dt.date(2026, 6, 12)) == dt.date(2026, 6, 18)   # still JUN
    assert cal.front_settlement(dt.date(2026, 6, 16)) == dt.date(2026, 9, 18)   # rolled to SEP
