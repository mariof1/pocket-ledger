"""Focused server tests for account isolation and money records."""

import copy
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch


TEST_DIR = tempfile.TemporaryDirectory()
os.environ["LEDGER_INSTANCE"] = TEST_DIR.name
from app import app, db, reset_account_password  # noqa: E402
from bill_import import due_dates  # noqa: E402
import commute as commute_module  # noqa: E402


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]

    def request(self, method, path, body=None):
        return self.client.open(path, method=method, json=body,
                                headers={"X-CSRF-Token": self.csrf})

    def register(self, email):
        response = self.request("POST", "/api/register",
                                {"email": email, "password": "a strong password 123"})
        self.assertEqual(response.status_code, 200)
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]

    def test_csrf_and_login_required(self):
        self.assertEqual(self.client.post("/api/register", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/data").status_code, 401)
        self.assertEqual(self.client.get("/api/account/export").status_code, 401)
        self.assertEqual(self.client.post("/api/account/import", json={}).status_code, 403)

    def test_account_export_import_preserves_profiles_records_and_bill_links(self):
        self.register("transfer-source@example.com")
        today = date.today()
        current_month = today.strftime("%Y-%m")
        self.assertEqual(self.request("POST", "/api/transactions", {
            "kind": "income", "amount": "2500", "category": "Salary",
            "occurred_on": today.isoformat(), "note": "Monthly pay"
        }).status_code, 201)
        self.assertEqual(self.request("POST", "/api/budgets", {
            "month": current_month, "category": "Housing", "limit": "900"
        }).status_code, 201)
        self.assertEqual(self.request("POST", "/api/goals", {
            "name": "Holiday", "target": "1200", "saved": "200",
            "monthly": "50", "target_date": "2027-06-01"
        }).status_code, 201)
        bill = self.request("POST", "/api/bills", {
            "name": "Rent", "category": "Housing", "amount": "700",
            "day_of_month": today.day
        })
        self.assertEqual(bill.status_code, 201)
        selection = [{"bill_id": bill.json["id"], "due_on": today.isoformat()}]
        self.assertEqual(self.request("POST", "/api/bills/import", {
            "month": current_month, "items": selection
        }).json["imported_count"], 1)
        self.assertEqual(self.request("POST", "/api/commutes", {
            "name": "Train", "mode": "public", "fare": "8.50",
            "weekdays": [0, 1, 2, 3, 4], "bank_holiday_region": "none",
            "leave_mode": "annual", "annual_leave_days": 25, "excluded_dates": ""
        }).status_code, 201)
        second = self.request("POST", "/api/profiles", {
            "name": "Travel", "currency": "EUR"
        })
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self.request("POST", "/api/transactions", {
            "kind": "expense", "amount": "3", "category": "Tickets",
            "occurred_on": today.isoformat(), "note": "Bus"
        }).status_code, 201)
        source = self.client.get("/api/account/export")
        self.assertEqual(source.status_code, 200)
        self.assertIn("attachment", source.headers["Content-Disposition"])
        document = source.json
        self.assertEqual((document["format"], document["version"], len(document["profiles"])),
                         ("pocket-ledger-account", 1, 2))
        self.assertNotIn("password_hash", str(document))
        self.assertNotIn("transfer-source@example.com", str(document))
        self.assertEqual(len(document["profiles"][0]["bill_imports"]), 1)

        destination = app.test_client()
        csrf = destination.get("/api/bootstrap").json["csrf"]
        self.assertEqual(destination.post("/api/register", json={
            "email": "transfer-destination@example.com", "password": "new account password 123"
        }, headers={"X-CSRF-Token": csrf}).status_code, 200)
        fresh_bootstrap = destination.get("/api/bootstrap").json
        self.assertTrue(fresh_bootstrap["import_ready"])
        csrf = fresh_bootstrap["csrf"]
        oversized_for_other_routes = copy.deepcopy(document)
        oversized_for_other_routes["padding"] = "x" * 40_000
        imported = destination.post("/api/account/import", json=oversized_for_other_routes,
                                    headers={"X-CSRF-Token": csrf})
        self.assertEqual(imported.status_code, 201, imported.json)
        self.assertEqual(imported.json["profiles"], 2)
        self.assertEqual(imported.json["counts"]["transactions"], 3)
        self.assertEqual(imported.json["counts"]["bill_imports"], 1)
        self.assertFalse(destination.get("/api/bootstrap").json["import_ready"])
        restored = destination.get("/api/account/export").json
        for before, after in zip(document["profiles"], restored["profiles"]):
            self.assertEqual((before["name"], before["currency"]),
                             (after["name"], after["currency"]))
            for resource in ("transactions", "budgets", "goals", "bills",
                             "commutes", "categories", "bill_imports"):
                self.assertEqual(len(before[resource]), len(after[resource]), resource)
            self.assertEqual(
                [{key: value for key, value in tx.items() if key != "id"}
                 for tx in before["transactions"]],
                [{key: value for key, value in tx.items() if key != "id"}
                 for tx in after["transactions"]])
        self.assertEqual(destination.post("/api/account/import", json=document,
                                         headers={"X-CSRF-Token": csrf}).status_code, 400)
        with app.app_context():
            self.assertEqual(db().execute("PRAGMA foreign_key_check").fetchall(), [])
            link = db().execute("""SELECT bills.name, transactions.note, bill_imports.due_on
                FROM bill_imports JOIN bills ON bills.id = bill_imports.bill_id
                JOIN transactions ON transactions.id = bill_imports.transaction_id
                JOIN profiles ON profiles.id = bills.profile_id JOIN users ON users.id = profiles.user_id
                WHERE users.email = ?""", ("transfer-destination@example.com",)).fetchone()
            self.assertEqual(tuple(link), ("Rent", "Rent", today.isoformat()))

    def test_bad_export_rolls_back_and_populated_account_refuses_import(self):
        self.register("transfer-invalid@example.com")
        original = self.client.get("/api/account/export").json
        invalid = copy.deepcopy(original)
        invalid["profiles"][0]["transactions"] = [{
            "id": 1, "kind": "expense", "amount_cents": 500, "category": "Food",
            "occurred_on": "2026-09-15", "note": "", "created_at": "2026-09-15 12:00:00"
        }, {
            "id": 2, "kind": "expense", "amount_cents": 500, "category": "Food",
            "occurred_on": "2026-02-30", "note": "", "created_at": "2026-09-15 12:00:00"
        }]
        response = self.request("POST", "/api/account/import", invalid)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/transactions").json["total"], 0)
        self.assertEqual(self.client.get("/api/account/export").json, original)
        self.assertTrue(self.client.get("/api/bootstrap").json["import_ready"])
        malformed_rows = (
            ("bills", {"id": 1, "name": "Rent", "category": "Housing",
                       "amount_cents": 70000, "day_of_month": 1,
                       "frequency": [], "first_due_on": None}),
            ("commutes", {"name": "Train", "mode": "public",
                          "distance_hundredths": 0, "mpg_hundredths": 0,
                          "fuel_price_cents": 0, "fare_cents": 850,
                          "weekdays": "0,1,2,3,4", "excluded_dates": "",
                          "bank_holiday_region": {}, "leave_mode": "dates",
                          "annual_leave_days": 0}),
        )
        for table, row in malformed_rows:
            bad = copy.deepcopy(original)
            bad["profiles"][0][table] = [row]
            response = self.request("POST", "/api/account/import", bad)
            self.assertEqual(response.status_code, 400, (table, response.data))
            self.assertEqual(self.client.get("/api/account/export").json, original)
        self.assertEqual(self.request("POST", "/api/transactions", {
            "kind": "expense", "amount": "2", "category": "Food",
            "occurred_on": date.today().isoformat()
        }).status_code, 201)
        self.assertEqual(self.request("POST", "/api/account/import", original).status_code, 400)
        self.assertFalse(self.client.get("/api/bootstrap").json["import_ready"])

    def test_records_are_separate_by_profile_and_account(self):
        self.register("first@example.com")
        original = self.client.get("/api/bootstrap").json["profile_id"]
        tx = self.request("POST", "/api/transactions", {
            "kind": "expense", "amount": "12.34", "category": "Groceries",
            "occurred_on": "2026-09-15", "note": "Market"
        })
        self.assertEqual(tx.status_code, 201)
        tx_id = tx.json["id"]
        self.assertEqual(self.client.get("/api/data?month=2026-09").json["monthly_totals"]["expense"], 1234)
        self.assertEqual(self.client.get("/api/transactions").json["transactions"][0]["amount_cents"], 1234)
        self.assertEqual(self.request("POST", "/api/budgets", {
            "month": "2026-09", "category": "Groceries", "limit": "200.00"
        }).status_code, 201)
        self.assertEqual(self.request("POST", "/api/goals", {
            "name": "Holiday", "target": "1000", "saved": "150", "monthly": "50"
        }).status_code, 201)
        self.assertEqual(self.request("POST", "/api/bills", {
            "name": "Rent", "category": "Housing", "amount": "750", "day_of_month": 1
        }).status_code, 201)
        profile = self.request("POST", "/api/profiles", {"name": "Household", "currency": "GBP"})
        self.assertEqual(profile.status_code, 201)
        data = self.client.get("/api/data?month=2026-09").json
        for resource in ("recent", "budgets", "goals", "bills"):
            self.assertEqual(data[resource], [])
        self.assertEqual(self.client.get("/api/transactions").json["transactions"], [])
        self.assertEqual(self.request("PUT", f"/api/transactions/{tx_id}", {
            "kind": "income", "amount": "50", "category": "Salary", "occurred_on": "2026-09-15"
        }).status_code, 404)
        self.assertEqual(self.request("DELETE", f"/api/transactions/{tx_id}").status_code, 404)
        self.assertEqual(self.request("POST", f"/api/profiles/{original}/select").status_code, 200)
        self.assertEqual(len(self.client.get("/api/transactions").json["transactions"]), 1)

        other = app.test_client()
        other_csrf = other.get("/api/bootstrap").json["csrf"]
        self.assertEqual(other.post("/api/register", json={"email": "second@example.com", "password": "another strong password"},
                                    headers={"X-CSRF-Token": other_csrf}).status_code, 200)
        self.assertEqual(other.get("/api/transactions").json["transactions"], [])
        other_csrf = other.get("/api/bootstrap").json["csrf"]
        self.assertEqual(other.post(f"/api/profiles/{original}/select", headers={"X-CSRF-Token": other_csrf}).status_code, 404)

    def test_validates_money_and_authentication(self):
        self.register("validation@example.com")
        self.assertEqual(self.request("POST", "/api/transactions", {
            "kind": "expense", "amount": "1.999", "category": "Other", "occurred_on": "2026-09-15"
        }).status_code, 400)
        self.assertEqual(self.request("POST", "/api/logout").status_code, 200)
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        self.assertEqual(self.request("POST", "/api/login", {
            "email": "validation@example.com", "password": "wrong password"
        }).status_code, 401)
        self.assertEqual(self.request("POST", "/api/login", {
            "email": "validation@example.com", "password": "a strong password 123"
        }).status_code, 200)

    def test_future_transactions_do_not_count_as_current_spending(self):
        self.register("future-transaction@example.com")
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        response = self.request("POST", "/api/transactions", {
            "kind": "expense", "amount": "20", "category": "Housing", "occurred_on": tomorrow
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("today or earlier", response.json["error"])
        self.assertEqual(self.client.get("/api/transactions").json["total"], 0)
        # A future-dated record saved by an older app version remains editable,
        # but does not inflate cash flow, chart, spending categories or recent activity.
        profile_id = self.client.get("/api/bootstrap").json["profile_id"]
        with app.app_context():
            db().execute("""INSERT INTO transactions(profile_id, kind, amount_cents,
                category, occurred_on, note) VALUES(?, 'expense', 2000, 'Housing', ?, '')""",
                (profile_id, tomorrow))
            db().commit()
        data = self.client.get(f"/api/data?month={tomorrow[:7]}").json
        self.assertEqual((data["monthly_totals"]["expense"], data["spending"], data["recent"]),
                         (0, [], []))
        self.assertEqual(data["chart"][-1]["expense"], 0)
        self.assertEqual(self.client.get("/api/transactions").json["total"], 1)

    def test_sign_in_attempts_are_limited(self):
        self.register("limit@example.com")
        self.assertEqual(self.request("POST", "/api/logout").status_code, 200)
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        for _ in range(5):
            self.assertEqual(self.request("POST", "/api/login", {
                "email": "limit@example.com", "password": "wrong password"
            }).status_code, 401)
        self.assertEqual(self.request("POST", "/api/login", {
            "email": "limit@example.com", "password": "a strong password 123"
        }).status_code, 429)

    def test_sign_out_revokes_a_copied_session_cookie(self):
        self.register("revocation@example.com")
        copied_cookie = self.client.get_cookie("session").value
        self.assertEqual(self.client.get("/api/data").status_code, 200)
        self.assertEqual(self.request("POST", "/api/logout").status_code, 200)
        replay = app.test_client()
        replay.set_cookie("session", copied_cookie)
        self.assertIsNone(replay.get("/api/bootstrap").json["user"])
        self.assertEqual(replay.get("/api/data").status_code, 401)

    def test_monthly_summaries_and_transaction_paging(self):
        self.register("paging@example.com")
        for index in range(53):
            response = self.request("POST", "/api/transactions", {
                "kind": "expense", "amount": "1.00", "category": "Coffee",
                "occurred_on": "2026-09-15", "note": f"Coffee #{index}"
            })
            self.assertEqual(response.status_code, 201)
        summary = self.client.get("/api/data?month=2026-09").json
        self.assertEqual(summary["monthly_totals"]["expense"], 5300)
        self.assertEqual(summary["spending"][0]["amount_cents"], 5300)
        self.assertEqual(len(summary["recent"]), 5)
        self.assertEqual(summary["chart"][-1]["expense"], 5300)
        first = self.client.get("/api/transactions").json
        self.assertEqual((first["total"], len(first["transactions"])), (53, 50))
        last = self.client.get("/api/transactions?offset=50").json
        self.assertEqual((last["total"], len(last["transactions"])), (53, 3))
        self.assertEqual(self.client.get("/api/transactions?search=Coffee%20%2352").json["total"], 1)
        self.assertEqual(self.client.get("/api/transactions?kind=income").json["total"], 0)
        self.assertEqual(self.client.get("/api/transactions?offset=-1").status_code, 400)

    def test_password_change_and_owner_reset_revoke_sessions(self):
        self.register("password@example.com")
        copied_cookie = self.client.get_cookie("session").value
        self.assertEqual(self.request("POST", "/api/password", {
            "current_password": "wrong", "new_password": "another strong password 456"
        }).status_code, 400)
        self.assertEqual(self.request("POST", "/api/password", {
            "current_password": "a strong password 123", "new_password": "another strong password 456"
        }).status_code, 200)
        old = app.test_client()
        old.set_cookie("session", copied_cookie)
        self.assertIsNone(old.get("/api/bootstrap").json["user"])
        self.assertEqual(self.client.get("/api/data").status_code, 200)
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        self.assertEqual(self.request("POST", "/api/logout").status_code, 200)
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        self.assertEqual(self.request("POST", "/api/login", {
            "email": "password@example.com", "password": "a strong password 123"
        }).status_code, 401)
        self.assertEqual(self.request("POST", "/api/login", {
            "email": "password@example.com", "password": "another strong password 456"
        }).status_code, 200)
        self.assertTrue(reset_account_password("password@example.com", "reset strong password 789"))
        self.assertIsNone(self.client.get("/api/bootstrap").json["user"])
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        self.assertEqual(self.request("POST", "/api/login", {
            "email": "password@example.com", "password": "reset strong password 789"
        }).status_code, 200)

    def test_malformed_record_fields_do_not_change_saved_data(self):
        self.register("fields@example.com")
        created = self.request("POST", "/api/transactions", {
            "kind": "expense", "amount": "12.00", "category": "Groceries",
            "occurred_on": "2026-09-15", "note": "Original"
        })
        self.assertEqual(created.status_code, 201)
        for note in ({"unexpected": "object"}, "x" * 201):
            self.assertEqual(self.request("PUT", f"/api/transactions/{created.json['id']}", {
                "kind": "expense", "amount": "99.00", "category": "Other",
                "occurred_on": "2026-09-15", "note": note
            }).status_code, 400)
        saved = self.client.get("/api/transactions").json["transactions"][0]
        self.assertEqual((saved["amount_cents"], saved["note"]), (1200, "Original"))
        for day in (1.5, True, "31.5"):
            self.assertEqual(self.request("POST", "/api/bills", {
                "name": "Bill", "category": "Housing", "amount": "20", "day_of_month": day
            }).status_code, 400)
        self.assertEqual(self.client.get("/api/data").json["bills"], [])
        self.assertEqual(self.client.get("/api/transactions?offset=99999999999999999999999").status_code, 400)

    def test_bill_category_can_be_reused_after_bill_is_deleted(self):
        self.register("categories@example.com")
        first = self.request("POST", "/api/bills", {
            "name": "Nursery", "category": "Childcare", "amount": "450", "day_of_month": 3
        })
        self.assertEqual(first.status_code, 201)
        self.assertIn("Childcare", self.client.get("/api/data").json["categories"])
        self.assertEqual(self.request("DELETE", f"/api/bills/{first.json['id']}").status_code, 200)
        self.assertIn("Childcare", self.client.get("/api/data").json["categories"])
        second = self.request("POST", "/api/bills", {
            "name": "School club", "category": "childcare", "amount": "80", "day_of_month": 8
        })
        self.assertEqual(second.status_code, 201)
        data = self.client.get("/api/data").json
        self.assertEqual(data["bills"][0]["category"], "Childcare")
        self.assertEqual(data["categories"].count("Childcare"), 1)
        self.assertEqual(self.request("POST", "/api/profiles", {
            "name": "Second profile", "currency": "GBP"
        }).status_code, 201)
        self.assertNotIn("Childcare", self.client.get("/api/data").json["categories"])

    def test_recurring_bills_have_consistent_monthly_planning_costs(self):
        self.register("recurring@example.com")
        cases = [
            ("Weekly shop", "20.00", "weekly", 8667),
            ("Annual cover", "120.00", "yearly", 1000),
            ("Quarterly service", "30.00", "quarterly", 1000),
            ("Fortnightly class", "10.00", "biweekly", 2167),
            ("Four-week plan", "12.00", "fourweekly", 1300),
            ("Daily fare", "2.00", "daily", 6083),
            ("Monthly rent", "750.00", "monthly", 75000),
        ]
        for name, amount, frequency, _ in cases:
            response = self.request("POST", "/api/bills", {
                "name": name, "category": "Housing", "amount": amount,
                "frequency": frequency, "day_of_month": 15
            })
            self.assertEqual(response.status_code, 201)
        data = self.client.get("/api/data?month=2026-09").json
        monthly = {bill["name"]: bill["monthly_cents"] for bill in data["bills"]}
        self.assertEqual(monthly, {name: expected for name, _, _, expected in cases})
        self.assertEqual(data["monthly_bills_cents"], sum(expected for _, _, _, expected in cases))
        self.assertEqual(self.client.get("/api/data?month=2026-10").json["monthly_bills_cents"],
                         data["monthly_bills_cents"])
        self.assertEqual(data["monthly_totals"]["expense"], 0)
        self.assertEqual(self.request("POST", "/api/transactions", {
            "kind": "expense", "amount": "20", "category": "Housing",
            "occurred_on": "2026-09-15", "note": "Weekly shop paid"
        }).status_code, 201)
        after_payment = self.client.get("/api/data?month=2026-09").json
        self.assertEqual(after_payment["monthly_bills_cents"], data["monthly_bills_cents"])
        self.assertEqual(after_payment["monthly_totals"]["expense"], 2000)
        weekly_id = next(bill["id"] for bill in data["bills"] if bill["name"] == "Weekly shop")
        self.assertEqual(self.request("PUT", f"/api/bills/{weekly_id}", {
            "name": "Weekly shop", "category": "Housing", "amount": "120",
            "frequency": "yearly"
        }).status_code, 200)
        updated = self.client.get("/api/data").json
        self.assertEqual(next(bill["monthly_cents"] for bill in updated["bills"]
                              if bill["id"] == weekly_id), 1000)
        self.assertEqual(self.request("PUT", f"/api/bills/{weekly_id}", {
            "name": "Weekly shop", "category": "Housing", "amount": "120",
            "frequency": "sometimes"
        }).status_code, 400)
        self.assertEqual(self.request("POST", "/api/profiles", {
            "name": "Other", "currency": "GBP"
        }).status_code, 201)
        self.assertEqual(self.client.get("/api/data").json["monthly_bills_cents"], 0)

    def test_existing_bill_table_upgrades_without_changing_monthly_bills(self):
        with tempfile.TemporaryDirectory() as legacy_dir:
            legacy_db = Path(legacy_dir) / "ledger.sqlite3"
            conn = sqlite3.connect(legacy_db)
            conn.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT);
                CREATE TABLE profiles (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, currency TEXT);
                CREATE TABLE bills (id INTEGER PRIMARY KEY, profile_id INTEGER, name TEXT,
                    category TEXT, amount_cents INTEGER, day_of_month INTEGER);
                INSERT INTO users VALUES (1, 'legacy@example.com', 'unused');
                INSERT INTO profiles VALUES (1, 1, 'Personal', 'GBP');
                INSERT INTO bills VALUES (1, 1, 'Council tax', 'Housing', 18000, 15);
            """)
            conn.close()
            environment = {**os.environ, "LEDGER_INSTANCE": legacy_dir}
            result = subprocess.run([sys.executable, "-c", "import app"],
                                    cwd=Path(__file__).resolve().parent,
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            conn = sqlite3.connect(legacy_db)
            self.assertEqual(conn.execute("SELECT frequency, amount_cents, day_of_month, first_due_on FROM bills"
                                          ).fetchone(), ("monthly", 18000, 15, None))
            self.assertEqual(conn.execute("SELECT name FROM sqlite_master WHERE name = 'bill_imports'"
                                          ).fetchone(), ("bill_imports",))
            conn.close()

    def test_bill_payment_schedule_uses_actual_occurrences(self):
        bill = {"frequency": "monthly", "day_of_month": 31, "first_due_on": None}
        self.assertEqual(due_dates(bill, "2026-02"), ["2026-02-28"])
        bill.update(frequency="weekly", first_due_on="2026-09-01")
        self.assertEqual(due_dates(bill, "2026-09"),
                         ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29"])
        bill.update(frequency="yearly", first_due_on="2024-02-29")
        self.assertEqual(due_dates(bill, "2026-02"), ["2026-02-28"])
        self.assertEqual(due_dates(bill, "2026-03"), [])
        bill.update(frequency="quarterly", first_due_on="2026-01-31")
        self.assertEqual(due_dates(bill, "2026-04"), ["2026-04-30"])

    def test_bill_import_preview_and_idempotent_actual_expenses(self):
        self.register("bill-import@example.com")
        monthly = self.request("POST", "/api/bills", {"name": "Rent", "category": "Housing",
            "amount": "750", "frequency": "monthly", "day_of_month": 10}).json["id"]
        weekly = self.request("POST", "/api/bills", {"name": "Lessons", "category": "Education",
            "amount": "12", "frequency": "weekly", "first_due_on": "2026-09-01"}).json["id"]
        unscheduled = self.request("POST", "/api/bills", {"name": "Insurance", "category": "Housing",
            "amount": "120", "frequency": "yearly"}).json["id"]
        preview = self.client.get("/api/bills/import-preview?month=2026-09").json
        self.assertEqual([item["due_on"] for item in preview["items"] if item["bill_id"] == weekly],
                         ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22", "2026-09-29"])
        self.assertEqual(preview["needs_schedule"][0]["id"], unscheduled)
        self.assertTrue(next(item for item in preview["items"] if item["due_on"] == "2026-09-22")["future"])
        selected = [{"bill_id": monthly, "due_on": "2026-09-10"},
                    {"bill_id": weekly, "due_on": "2026-09-08"}]
        result = self.request("POST", "/api/bills/import", {"month": "2026-09", "items": selected})
        self.assertEqual((result.status_code, result.json["imported_count"]), (201, 2))
        self.assertEqual(self.client.get("/api/data?month=2026-09").json["monthly_totals"]["expense"], 76200)
        transactions = self.client.get("/api/transactions?month=2026-09").json["transactions"]
        self.assertEqual({(tx["occurred_on"], tx["amount_cents"], tx["category"]) for tx in transactions},
                         {("2026-09-10", 75000, "Housing"), ("2026-09-08", 1200, "Education")})
        again = self.request("POST", "/api/bills/import", {"month": "2026-09", "items": selected})
        self.assertEqual((again.json["imported_count"], again.json["skipped_count"]), (0, 2))
        self.assertEqual(len(self.client.get("/api/transactions?month=2026-09").json["transactions"]), 2)
        self.assertTrue(next(item for item in self.client.get("/api/bills/import-preview?month=2026-09").json["items"]
                             if item["bill_id"] == monthly)["already_imported"])
        weekly_tx = next(tx for tx in transactions if tx["amount_cents"] == 1200)
        self.assertEqual(self.request("DELETE", f"/api/transactions/{weekly_tx['id']}").status_code, 200)
        self.assertEqual(self.request("POST", "/api/bills/import", {"month": "2026-09",
            "items": [{"bill_id": weekly, "due_on": "2026-09-08"}]}).json["imported_count"], 1)
        self.assertEqual(self.request("DELETE", f"/api/bills/{monthly}").status_code, 200)
        self.assertEqual(len(self.client.get("/api/transactions?month=2026-09").json["transactions"]), 2)

    def test_bill_import_flags_manual_expense_and_rejects_invalid_selection(self):
        self.register("bill-import-guard@example.com")
        profile = self.client.get("/api/bootstrap").json["profile_id"]
        bill_id = self.request("POST", "/api/bills", {"name": "Utilities", "category": "Housing",
            "amount": "40", "day_of_month": 10}).json["id"]
        self.assertEqual(self.request("POST", "/api/transactions", {"kind": "expense", "amount": "40",
            "category": "Housing", "occurred_on": "2026-09-10"}).status_code, 201)
        preview = self.client.get("/api/bills/import-preview?month=2026-09").json
        self.assertTrue(preview["items"][0]["possible_duplicate"])
        self.assertEqual(self.request("POST", "/api/bills/import", {"month": "2026-09",
            "items": [{"bill_id": bill_id, "due_on": "2026-09-11"}]}).status_code, 400)
        self.assertEqual(self.request("POST", "/api/bills/import", {"month": "2026-09",
            "items": [{"bill_id": bill_id, "due_on": "2026-09-20"}]}).status_code, 400)
        self.assertEqual(self.request("POST", "/api/bills/import", {"month": "2026-09",
            "items": [{"bill_id": bill_id, "due_on": "2026-09-10"}]},
            ).status_code, 201)
        self.assertEqual(self.request("POST", "/api/profiles", {"name": "Other", "currency": "GBP"}).status_code, 201)
        self.assertEqual(self.client.get("/api/bills/import-preview?month=2026-09").json["items"], [])
        self.assertEqual(self.request("POST", "/api/bills/import", {"month": "2026-09",
            "items": [{"bill_id": bill_id, "due_on": "2026-09-10"}]}).status_code, 400)
        self.assertEqual(self.request("POST", f"/api/profiles/{profile}/select").status_code, 200)

    def test_commuting_car_calendar_leave_and_profile_isolation(self):
        self.register("commute-car@example.com")
        original_profile = self.client.get("/api/bootstrap").json["profile_id"]
        form = {"name": "Office", "mode": "car", "distance": "30", "mpg": "40",
                "fuel_price": "1.50", "weekdays": ["0", "1", "2", "3", "4"],
                "excluded_dates": "2026-09-14..2026-09-18\n2026-09-21",
                "bank_holiday_region": "none"}
        response = self.request("POST", "/api/commutes", form)
        self.assertEqual(response.status_code, 201)
        commute_id = response.json["id"]
        september = self.client.get("/api/data?month=2026-09").json
        plan = next(item for item in september["commutes"] if item["id"] == commute_id)
        self.assertEqual((plan["candidate_days"], plan["leave_days"], plan["workdays"]),
                         (22, 6, 16))
        self.assertEqual((plan["daily_cents"], plan["monthly_cents"]), (511, 8176))
        self.assertEqual(plan["excluded_dates"], form["excluded_dates"])
        self.assertEqual(september["monthly_bills_cents"],
                         sum(item["monthly_cents"] for item in september["bills"]) + 8176)
        october = self.client.get("/api/data?month=2026-10").json
        self.assertEqual(next(item for item in october["commutes"]
                              if item["id"] == commute_id)["monthly_cents"], 22 * 511)
        self.assertEqual(self.request("POST", "/api/profiles", {
            "name": "Separate commute", "currency": "GBP"}).status_code, 201)
        self.assertEqual(self.client.get("/api/data?month=2026-09").json["commutes"], [])
        self.assertEqual(self.request("DELETE", f"/api/commutes/{commute_id}").status_code, 404)
        self.assertEqual(self.request("POST", f"/api/profiles/{original_profile}/select").status_code, 200)
        self.assertEqual(self.request("DELETE", f"/api/commutes/{commute_id}").status_code, 200)
        self.assertEqual(self.client.get("/api/data?month=2026-09").json["commutes"], [])

    def test_commuting_public_transport_and_bank_holidays(self):
        self.register("commute-train@example.com")
        form = {"name": "Train", "mode": "public", "fare": "8.50",
                "weekdays": ["0", "1", "2", "3", "4"], "excluded_dates": "",
                "bank_holiday_region": "england-and-wales"}
        official = {"england-and-wales": {"events": [
            {"date": "2026-08-31"}, {"date": "2026-12-25"}]}}
        with patch("app.official_holidays", return_value=(official, None)):
            preview = self.request("POST", "/api/commutes/preview", {**form, "month": "2026-08"})
            self.assertEqual(preview.status_code, 200)
            self.assertEqual((preview.json["candidate_days"], preview.json["bank_holiday_days"],
                              preview.json["workdays"], preview.json["monthly_cents"]),
                             (21, 1, 20, 17000))
            response = self.request("POST", "/api/commutes", form)
            self.assertEqual(response.status_code, 201)
            commute_id = response.json["id"]
            self.assertEqual(self.client.get("/api/data?month=2026-08").json[
                "monthly_commuting_cents"], 17000)
        with patch("app.official_holidays", return_value=(None, "Offline")):
            unavailable = self.client.get("/api/data?month=2026-08").json["commutes"][0]
            self.assertIsNotNone(unavailable["holiday_status"])
            self.assertEqual(unavailable["monthly_cents"], 21 * 850)
        updated = {**form, "bank_holiday_region": "none", "weekdays": ["5", "6"]}
        self.assertEqual(self.request("PUT", f"/api/commutes/{commute_id}", updated).status_code, 200)
        weekends = self.client.get("/api/data?month=2026-08").json["commutes"][0]
        self.assertEqual(weekends["workdays"], 10)

    def test_commuting_rejects_bad_schedule_and_money_inputs(self):
        self.register("commute-invalid@example.com")
        valid = {"name": "Drive", "mode": "car", "distance": "20", "mpg": "40",
                 "fuel_price": "1.50", "weekdays": ["0"], "excluded_dates": "",
                 "bank_holiday_region": "none"}
        for change in ({"weekdays": []}, {"distance": "-5"}, {"mpg": "0"},
                       {"fuel_price": "1.123"}, {"bank_holiday_region": "unknown"},
                       {"bank_holiday_region": []},
                       {"excluded_dates": "2026-09-31"},
                       {"excluded_dates": "2026-09-20..2026-09-10"}):
            self.assertEqual(self.request("POST", "/api/commutes", {**valid, **change}).status_code, 400)
        self.assertEqual(self.client.get("/api/data?month=2026-09").json["commutes"], [])

    def test_annual_leave_allowance_is_spread_across_commuting_months(self):
        self.register("annual-leave@example.com")
        form = {"name": "Office drive", "mode": "car", "distance": "30", "mpg": "40",
                "fuel_price": "1.50", "weekdays": ["0", "1", "2", "3", "4"],
                "bank_holiday_region": "none", "leave_mode": "annual",
                "annual_leave_days": 25}
        preview = self.request("POST", "/api/commutes/preview", {**form, "month": "2026-09"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual((preview.json["workdays"], preview.json["expected_days"],
                          preview.json["annual_leave_estimate_days"], preview.json["monthly_cents"]),
                         (22, 19.89, 2.11, 10165))
        response = self.request("POST", "/api/commutes", form)
        self.assertEqual(response.status_code, 201)
        commute_id = response.json["id"]
        plan = self.client.get("/api/data?month=2026-09").json["commutes"][0]
        self.assertEqual((plan["leave_mode"], plan["annual_leave_days"],
                          plan["excluded_dates"], plan["monthly_cents"]),
                         ("annual", 25, "", 10165))
        august = self.client.get("/api/data?month=2026-08").json["commutes"][0]
        self.assertEqual(august["workdays"], 21)
        self.assertLess(august["monthly_cents"], plan["monthly_cents"])
        # Switching back to exact dates replaces the allowance; neither is double-counted.
        exact = {**form, "leave_mode": "dates", "annual_leave_days": 0,
                 "excluded_dates": "2026-09-14..2026-09-18"}
        self.assertEqual(self.request("PUT", f"/api/commutes/{commute_id}", exact).status_code, 200)
        converted = self.client.get("/api/data?month=2026-09").json["commutes"][0]
        self.assertEqual((converted["workdays"], converted["monthly_cents"],
                          converted["annual_leave_days"]), (17, 8687, 0))

    def test_annual_leave_excludes_bank_holidays_first(self):
        self.register("annual-bank@example.com")
        form = {"name": "Train", "mode": "public", "fare": "8.50",
                "weekdays": ["0", "1", "2", "3", "4"],
                "bank_holiday_region": "england-and-wales",
                "leave_mode": "annual", "annual_leave_days": "25"}
        official = {"england-and-wales": {"events": [
            {"date": "2026-08-31"}, {"date": "2026-12-25"}]}}
        with patch("app.official_holidays", return_value=(official, None)):
            response = self.request("POST", "/api/commutes/preview", {**form, "month": "2026-08"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual((response.json["candidate_days"], response.json["bank_holiday_days"],
                              response.json["workdays"], response.json["expected_days"],
                              response.json["monthly_cents"]),
                             (21, 1, 20, 18.07, 15359))
        for change in ({"annual_leave_days": "25.5"}, {"annual_leave_days": 366},
                       {"annual_leave_days": True}, {"excluded_dates": "2026-08-10"},
                       {"leave_mode": "unknown"}):
            self.assertEqual(self.request("POST", "/api/commutes", {**form, **change}).status_code, 400)

    def test_offline_bank_holiday_source_retries_after_short_backoff(self):
        with patch.object(commute_module, "_holiday_cache", None), \
             patch.object(commute_module, "_holiday_fetched_at", 0), \
             patch.object(commute_module, "_holiday_failed_at", 0), \
             patch.object(commute_module.time, "time", return_value=1000), \
             patch.object(commute_module, "urlopen", side_effect=OSError("offline")) as fetch:
            first = commute_module.official_holidays()
            second = commute_module.official_holidays()
            self.assertEqual(first, second)
            self.assertEqual(fetch.call_count, 1)

    def test_existing_commuting_plans_upgrade_to_exact_dates(self):
        with tempfile.TemporaryDirectory() as legacy_dir:
            legacy_db = Path(legacy_dir) / "ledger.sqlite3"
            conn = sqlite3.connect(legacy_db)
            conn.executescript("""
                CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT);
                CREATE TABLE profiles (id INTEGER PRIMARY KEY, user_id INTEGER, name TEXT, currency TEXT);
                CREATE TABLE commutes (id INTEGER PRIMARY KEY, profile_id INTEGER,
                    name TEXT, mode TEXT, distance_hundredths INTEGER, mpg_hundredths INTEGER,
                    fuel_price_cents INTEGER, fare_cents INTEGER, weekdays TEXT,
                    excluded_dates TEXT, bank_holiday_region TEXT);
                INSERT INTO users VALUES (1, 'legacy-commute@example.com', 'unused');
                INSERT INTO profiles VALUES (1, 1, 'Personal', 'GBP');
                INSERT INTO commutes VALUES (1, 1, 'Office', 'car', 3000, 4000,
                    150, 0, '0,1,2,3,4', '2026-09-14..2026-09-18', 'none');
            """)
            conn.close()
            environment = {**os.environ, "LEDGER_INSTANCE": legacy_dir}
            result = subprocess.run([sys.executable, "-c", "import app"],
                                    cwd=Path(__file__).resolve().parent,
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            conn = sqlite3.connect(legacy_db)
            self.assertEqual(conn.execute("""SELECT name, weekdays, excluded_dates,
                leave_mode, annual_leave_days FROM commutes WHERE id = 1""").fetchone(),
                             ("Office", "0,1,2,3,4", "2026-09-14..2026-09-18", "dates", 0))
            conn.close()


if __name__ == "__main__":
    unittest.main()
