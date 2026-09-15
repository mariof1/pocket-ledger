"""Calendar-month estimates for saved commuting plans."""

import calendar
import json
import re
import threading
import time
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.request import Request, urlopen


REGIONS = {"none", "england-and-wales", "scotland", "northern-ireland"}
UK_GALLON_LITRES = Decimal("4.54609")
_holiday_cache = None
_holiday_fetched_at = 0
_holiday_failed_at = 0
_holiday_lock = threading.Lock()


def positive_hundredths(value, label, maximum):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number.as_tuple().exponent < -2:
            raise ValueError
        units = int(number * 100)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be a positive number with at most two decimals.")
    if not 0 < units <= maximum * 100:
        raise ValueError(f"{label} is out of range.")
    return units


def parse_dates(value):
    """Accept one ISO date or inclusive ISO date range per line."""
    if not isinstance(value, str) or len(value) > 10000:
        raise ValueError("Dates off must be a short list of dates or date ranges.")
    result = set()
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("..")
        if len(parts) not in (1, 2):
            raise ValueError("Use YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD for dates off.")
        if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", part.strip()) for part in parts):
            raise ValueError("Use YYYY-MM-DD or YYYY-MM-DD..YYYY-MM-DD for dates off.")
        try:
            start = date.fromisoformat(parts[0].strip())
            end = date.fromisoformat(parts[-1].strip())
        except ValueError:
            raise ValueError("Use valid YYYY-MM-DD dates for dates off.")
        length = (end - start).days
        if not 0 <= length <= 366:
            raise ValueError("Each date range must be at most 366 days and end after it starts.")
        for offset in range(length + 1):
            result.add((start + timedelta(days=offset)).isoformat())
        if len(result) > 2000:
            raise ValueError("Dates off can contain at most 2,000 days.")
    return sorted(result)


def official_holidays():
    """Fetch GOV.UK's official JSON; cache successful responses for a day."""
    global _holiday_cache, _holiday_fetched_at, _holiday_failed_at
    with _holiday_lock:
        if _holiday_cache is not None and time.time() - _holiday_fetched_at < 86400:
            return _holiday_cache, None
        if time.time() - _holiday_failed_at < 300:
            return _holiday_cache, "Official bank holiday data could not be refreshed."
        try:
            req = Request("https://www.gov.uk/bank-holidays.json",
                          headers={"User-Agent": "PocketLedger/1.0"})
            with urlopen(req, timeout=3) as response:
                document = json.load(response)
            if not isinstance(document, dict) or not all(
                    isinstance(document.get(region, {}).get("events"), list)
                    for region in REGIONS - {"none"}):
                raise ValueError("Invalid bank holiday data")
            _holiday_cache, _holiday_fetched_at = document, time.time()
            _holiday_failed_at = 0
            return document, None
        except Exception:
            _holiday_failed_at = time.time()
            return _holiday_cache, "Official bank holiday data could not be refreshed."


def estimate(plan, month, holidays=None, holiday_error=None):
    year, number = map(int, month.split("-"))
    last_day = calendar.monthrange(year, number)[1]
    selected = {int(day) for day in plan["weekdays"].split(",")}
    leave = set(parse_dates(plan["excluded_dates"]))
    bank = set()
    status = None
    region = plan["bank_holiday_region"]
    if region != "none":
        if holidays is None:
            status = holiday_error or "Official bank holiday data is unavailable; check this estimate."
        else:
            events = holidays.get(region, {}).get("events", [])
            bank = {event["date"] for event in events if isinstance(event, dict)
                    and isinstance(event.get("date"), str)
                    and re.fullmatch(r"\d{4}-\d{2}-\d{2}", event["date"])}
            if not any(day and day.startswith(f"{year:04d}-") for day in bank):
                status = f"Official bank holiday dates for {year} are unavailable; check this estimate."
            elif holiday_error:
                status = "Using cached GOV.UK bank holiday dates; check for updates."
    candidate = leave_days = bank_days = workdays = 0
    leave_mode = plan.get("leave_mode", "dates")
    for day in range(1, last_day + 1):
        current = date(year, number, day)
        if current.weekday() not in selected:
            continue
        candidate += 1
        key = current.isoformat()
        if key in bank:
            bank_days += 1
        elif leave_mode == "dates" and key in leave:
            leave_days += 1
        else:
            workdays += 1
    if plan["mode"] == "car":
        # UK mpg uses imperial gallons. All car inputs are stored as hundredths.
        miles = Decimal(plan["distance_hundredths"]) / 100
        mpg = Decimal(plan["mpg_hundredths"]) / 100
        price = Decimal(plan["fuel_price_cents"]) / 100
        daily_cents = int((miles / mpg * UK_GALLON_LITRES * price * 100)
                          .quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    else:
        daily_cents = plan["fare_cents"]
    annual_leave_estimate = Decimal("0")
    expected_days = Decimal(workdays)
    leave_status = None
    if leave_mode == "annual":
        first = date(year, 1, 1)
        days_in_year = 366 if calendar.isleap(year) else 365
        available_in_year = sum(
            1 for offset in range(days_in_year)
            if (current := first + timedelta(days=offset)).weekday() in selected
            and current.isoformat() not in bank)
        annual_days = plan["annual_leave_days"]
        if annual_days > available_in_year:
            leave_status = ("Annual leave exceeds this year's scheduled commuting days; "
                            "the estimate uses all available days off.")
        fraction = min(Decimal("1"), Decimal(annual_days) / Decimal(available_in_year))
        annual_leave_estimate = Decimal(workdays) * fraction
        expected_days -= annual_leave_estimate
    monthly_cents = int((expected_days * daily_cents).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))
    return {"candidate_days": candidate, "leave_days": leave_days,
            "bank_holiday_days": bank_days, "workdays": workdays,
            "annual_leave_estimate_days": float(annual_leave_estimate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "expected_days": float(expected_days.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
            "daily_cents": daily_cents, "monthly_cents": monthly_cents,
            "holiday_status": status, "leave_status": leave_status}
