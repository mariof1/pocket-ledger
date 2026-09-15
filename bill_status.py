"""Summarise scheduled bill occurrences separately from actual cash flow."""

from bill_import import due_dates


def month_bill_status(bills, linked_transactions, month, today):
    linked = {(item["bill_id"], item["due_on"]): item["amount_cents"]
              for item in linked_transactions}
    result = {"scheduled_cents": 0, "recorded_schedule_cents": 0,
              "recorded_cents": 0,
              "unrecorded_cents": 0, "due_now_cents": 0,
              "upcoming_cents": 0, "scheduled_count": 0,
              "recorded_count": 0, "unrecorded_count": 0,
              "unscheduled_bills": 0, "next_unrecorded": []}
    unrecorded = []
    for bill in bills:
        if bill["frequency"] != "monthly" and not bill["first_due_on"]:
            result["unscheduled_bills"] += 1
            continue
        for due_on in due_dates(bill, month):
            amount = bill["amount_cents"]
            result["scheduled_cents"] += amount
            result["scheduled_count"] += 1
            if (bill["id"], due_on) in linked:
                result["recorded_schedule_cents"] += amount
                result["recorded_cents"] += linked[(bill["id"], due_on)]
                result["recorded_count"] += 1
            else:
                result["unrecorded_cents"] += amount
                result["unrecorded_count"] += 1
                result["due_now_cents" if due_on <= today else "upcoming_cents"] += amount
                unrecorded.append({"bill_id": bill["id"], "name": bill["name"],
                                   "due_on": due_on, "amount_cents": amount,
                                   "due_now": due_on <= today})
    result["next_unrecorded"] = sorted(
        unrecorded, key=lambda item: (item["due_on"], item["name"].casefold(), item["bill_id"]))[:3]
    return result
