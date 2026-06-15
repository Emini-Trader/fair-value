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
