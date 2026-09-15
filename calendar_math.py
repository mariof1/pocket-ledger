"""Pure monthly schedule conversions and month boundaries."""

import re


BILL_FREQUENCIES = {
    "daily": (365, 12), "weekly": (52, 12), "biweekly": (26, 12),
    "fourweekly": (13, 12), "monthly": (1, 1),
    "quarterly": (1, 3), "yearly": (1, 12),
}


def monthly_bill_cents(amount_cents, frequency):
    numerator, denominator = BILL_FREQUENCIES[frequency]
    return (amount_cents * numerator + denominator // 2) // denominator


def month_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value) or value[:4] == "0000":
        raise ValueError("Month must use YYYY-MM format.")
    return value


def month_span(month):
    year, number = map(int, month.split("-"))
    next_year, next_number = (year + 1, 1) if number == 12 else (year, number + 1)
    upper = f"{next_year:04d}-{next_number:02d}-01" if next_year <= 9999 else "9999-12-32"
    keys = []
    for back in range(5, -1, -1):
        previous_year, previous_month = divmod(year * 12 + number - 1 - back, 12)
        keys.append(f"{previous_year:04d}-{previous_month + 1:02d}")
    return f"{month}-01", upper, keys
