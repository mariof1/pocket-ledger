"""Parse bank CSV exports and find likely duplicate ledger transactions."""

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


MAX_ROWS = 500
MAX_COLUMNS = 30


def csv_table(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Choose a non-empty CSV statement.")
    if "\x00" in text or len(text.encode("utf-8")) > 1_000_000:
        raise ValueError("The CSV file must be 1 MB or smaller.")
    text = text.lstrip("\ufeff")
    candidates = []
    for delimiter in (",", ";", "\t"):
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter,
                                   strict=True))
        except csv.Error:
            continue
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        if rows and 2 <= len(rows[0]) <= MAX_COLUMNS and len(rows) >= 2:
            width = len(rows[0])
            consistency = sum(len(row) == width for row in rows[1:min(len(rows), 11)])
            candidates.append((consistency, width, delimiter, rows))
    if not candidates:
        raise ValueError("The file needs a header and at least one CSV row.")
    _, width, delimiter, rows = max(candidates, key=lambda item: (item[0], item[1]))
    if len(rows) - 1 > MAX_ROWS:
        raise ValueError(f"Import up to {MAX_ROWS} statement rows at a time.")
    if any(len(row) != width for row in rows[1:]):
        raise ValueError("CSV rows have different numbers of columns. Check the selected file.")
    headers = [cell.strip()[:80] or f"Column {index + 1}" for index, cell in enumerate(rows[0])]
    if any(len(cell) > 500 for row in rows[1:] for cell in row):
        raise ValueError("A CSV cell is too long to review safely.")
    return headers, rows[1:], delimiter


def suggest_mapping(headers):
    patterns = {
        "date": ("date", "transactiondate", "bookingdate", "posteddate"),
        "description": ("description", "details", "narrative", "merchant", "payee", "reference"),
        "amount": ("amount", "transactionamount", "value"),
        "debit": ("debit", "withdrawal", "moneyout", "paidout"),
        "credit": ("credit", "deposit", "moneyin", "paidin"),
        "category": ("category", "type"),
    }
    mapping = {}
    for key, aliases in patterns.items():
        for index, header in enumerate(headers):
            normalized = re.sub(r"[^a-z0-9]", "", header.lower())
            if normalized in aliases or (key in ("date", "description") and
                                         any(normalized.startswith(alias) for alias in aliases)):
                mapping[key] = index
                break
    if "debit" in mapping and "credit" in mapping:
        mapping.pop("amount", None)
    return mapping


def validate_mapping(mapping, count):
    if not isinstance(mapping, dict):
        raise ValueError("Choose statement columns before previewing.")
    cleaned = {}
    for key in ("date", "description", "amount", "debit", "credit", "category"):
        value = mapping.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < count:
            raise ValueError("Choose columns from this CSV header.")
        cleaned[key] = value
    if "date" not in cleaned or not ("amount" in cleaned or "debit" in cleaned or "credit" in cleaned):
        raise ValueError("Map a date and either an amount or debit/credit columns.")
    if "amount" in cleaned and ("debit" in cleaned or "credit" in cleaned):
        raise ValueError("Use one signed Amount column or separate Debit/Credit columns.")
    if len(set(cleaned.values())) != len(cleaned):
        raise ValueError("Each field needs a different CSV column.")
    return cleaned


def parse_date(value, order):
    value = value.strip()
    if not value:
        raise ValueError("Date is empty.")
    if order not in ("dmy", "mdy", "ymd"):
        raise ValueError("Choose a date order.")
    value = value[:10] if re.match(r"^\d{4}-\d{2}-\d{2}[ T]", value) else value
    patterns = {"dmy": ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"),
                "mdy": ("%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y", "%m/%d/%y"),
                "ymd": ("%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d")}[order]
    for pattern in ("%Y-%m-%d", *patterns):
        try:
            result = datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
        if result > date.today().isoformat():
            raise ValueError("Future transactions cannot be imported.")
        return result
    raise ValueError("Date does not match the selected order.")


def parse_amount(value, decimal_mark):
    value = value.strip().replace("£", "").replace("€", "").replace("$", "")
    if not value:
        return None
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
        if value.startswith(("+", "-")):
            raise ValueError("Amount has two sign markers.")
    value = value.replace(" ", "").replace("\u00a0", "")
    if decimal_mark == "dot":
        if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?", value):
            raise ValueError("Amount does not match dot-decimal formatting.")
        value = value.replace(",", "")
    elif decimal_mark == "comma":
        if not re.fullmatch(r"[+-]?(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?", value):
            raise ValueError("Amount does not match comma-decimal formatting.")
        value = value.replace(".", "").replace(",", ".")
    else:
        raise ValueError("Choose a decimal separator.")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("Amount is not a number.")
    if not amount.is_finite() or amount.as_tuple().exponent < -2:
        raise ValueError("Amount needs at most two decimals.")
    cents = int(amount * 100) * (-1 if negative else 1)
    if not cents:
        return None
    if abs(cents) > 10_000_000_000:
        raise ValueError("Amount is out of range.")
    return cents


def normalize_note(value):
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def duplicate_for(item, existing):
    """Return exact/probable matches. Require amount and direction for every match."""
    note = normalize_note(item.get("note", ""))
    category = item.get("category", "").casefold()
    probable = False
    for other in existing:
        if other["kind"] != item["kind"] or other["amount_cents"] != item["amount_cents"]:
            continue
        days = abs((date.fromisoformat(other["occurred_on"]) -
                    date.fromisoformat(item["occurred_on"])).days)
        if days > 3:
            continue
        other_note = normalize_note(other.get("note", ""))
        if days == 0 and note and other_note and note == other_note:
            return "exact"
        if days == 0 and not note and not other_note and category == other["category"].casefold():
            return "exact"
        if note and other_note and (note == other_note or
                                    (len(note) >= 5 and len(other_note) >= 5 and
                                     (note in other_note or other_note in note))):
            probable = True
        if days == 0 and category == other["category"].casefold():
            probable = True
    return "probable" if probable else None


def statement_rows(headers, rows, mapping, date_order, decimal_mark, positive_expense,
                   category_suggestions=None):
    mapping = validate_mapping(mapping, len(headers))
    if not isinstance(positive_expense, bool):
        raise ValueError("Choose how signed amounts represent spending.")
    suggestions = category_suggestions or {}
    result = []
    for row_number, cells in enumerate(rows, 2):
        raw_date = cells[mapping["date"]].strip()
        raw_note = cells[mapping["description"]].strip() if "description" in mapping else ""
        raw_category = cells[mapping["category"]].strip() if "category" in mapping else ""
        if "amount" in mapping:
            raw_amount = cells[mapping["amount"]].strip()
        else:
            raw_amount = (cells[mapping["debit"]].strip() if "debit" in mapping else "") or \
                         (cells[mapping["credit"]].strip() if "credit" in mapping else "")
        item = {"row_number": row_number, "raw_date": raw_date, "raw_amount": raw_amount,
                "note": raw_note[:200], "category": raw_category[:40], "include": False}
        try:
            occurred_on = parse_date(raw_date, date_order)
            if "amount" in mapping:
                signed = parse_amount(raw_amount, decimal_mark)
                if signed is None:
                    raise ValueError("Amount is empty.")
                kind = "expense" if (signed > 0) == positive_expense else "income"
            else:
                debit = parse_amount(cells[mapping["debit"]], decimal_mark) if "debit" in mapping else None
                credit = parse_amount(cells[mapping["credit"]], decimal_mark) if "credit" in mapping else None
                if bool(debit) == bool(credit):
                    raise ValueError("Use either Debit or Credit for each row.")
                signed = debit if debit else credit
                kind = "expense" if debit else "income"
            amount_cents = abs(signed)
            item.update(occurred_on=occurred_on, kind=kind, amount_cents=amount_cents,
                        amount=f"{amount_cents // 100}.{amount_cents % 100:02d}")
            if not item["category"]:
                item["category"] = suggestions.get((kind, normalize_note(raw_note)),
                                                   "Other" if kind == "expense" else "Salary")
            item["include"] = True
        except ValueError as error:
            item["error"] = str(error)
        result.append(item)
    return result
