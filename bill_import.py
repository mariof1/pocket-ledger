"""Calculate actual scheduled bill payment dates for a calendar month."""

import calendar
from datetime import date, timedelta


DAY_INTERVALS = {
    "daily": 1, "weekly": 7, "biweekly": 14, "fourweekly": 28,
}
MONTH_INTERVALS = {"quarterly": 3, "yearly": 12}


def due_dates(bill, month):
    year, number = map(int, month.split("-"))
    last = calendar.monthrange(year, number)[1]
    start, end = date(year, number, 1), date(year, number, last)
    frequency = bill["frequency"]
    if frequency == "monthly":
        return [date(year, number, min(bill["day_of_month"], last)).isoformat()]
    if not bill["first_due_on"]:
        return []
    anchor = date.fromisoformat(bill["first_due_on"])
    if frequency in DAY_INTERVALS:
        interval = DAY_INTERVALS[frequency]
        offset = max(0, ((start - anchor).days + interval - 1) // interval)
        current = anchor + timedelta(days=offset * interval)
        result = []
        while current <= end:
            result.append(current.isoformat())
            if (end - current).days < interval:
                break
            current += timedelta(days=interval)
        return result
    step = MONTH_INTERVALS[frequency]
    months_since_anchor = (year - anchor.year) * 12 + number - anchor.month
    if months_since_anchor < 0 or months_since_anchor % step:
        return []
    current = date(year, number, min(anchor.day, last))
    return [current.isoformat()] if current >= anchor else []
