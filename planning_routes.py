"""Planning routes."""

def register_routes(app, core):
    # Bind the shared database and request helpers without importing app.py twice.
    BILL_FREQUENCIES = core["BILL_FREQUENCIES"]
    re = core["re"]
    iso_date = core["iso_date"]
    clean_text = core["clean_text"]
    money = core["money"]
    payload = core["payload"]
    current_profile = core["current_profile"]
    remember_category = core["remember_category"]
    db = core["db"]
    jsonify = core["jsonify"]
    fail = core["fail"]
    delete_owned = core["delete_owned"]
    bill_due_dates = core["bill_due_dates"]
    month_value = core["month_value"]
    request = core["request"]
    date = core["date"]
    month_span = core["month_span"]
    owned_account = core["owned_account"]
    sqlite3 = core["sqlite3"]
    REGIONS = core["REGIONS"]
    parse_dates = core["parse_dates"]
    positive_hundredths = core["positive_hundredths"]
    commute_estimate = core["commute_estimate"]
    official_holidays = lambda: core["official_holidays"]()

    def bill_fields(data):
        frequency = data.get("frequency", "monthly")
        if not isinstance(frequency, str) or frequency not in BILL_FREQUENCIES:
            raise ValueError("Choose a valid bill frequency.")
        raw_day = data.get("day_of_month", 1 if frequency != "monthly" else None)
        if isinstance(raw_day, bool) or not isinstance(raw_day, (int, str)) or not re.fullmatch(r"\d{1,2}", str(raw_day)):
            raise ValueError("Bill day must be a whole number from 1 to 31.")
        try:
            day = int(raw_day)
        except (TypeError, ValueError):
            raise ValueError("Bill day must be a whole number from 1 to 31.")
        if day < 1 or day > 31:
            raise ValueError("Bill day must be a whole number from 1 to 31.")
        first_due = iso_date(data.get("first_due_on"), "First payment date", optional=True)
        if frequency == "monthly":
            first_due = None
        return (clean_text(data.get("name"), "Bill name", 60),
                clean_text(data.get("category"), "Category", 40),
                money(data.get("amount"), "Amount each time"), day, frequency, first_due)


    @app.post("/api/bills")
    def add_bill():
        try:
            fields = bill_fields(payload())
            profile_id = current_profile()["id"]
            category = remember_category(profile_id, fields[1])
            fields = (fields[0], category, fields[2], fields[3], fields[4], fields[5])
            cursor = db().execute(
                "INSERT INTO bills(profile_id, name, category, amount_cents, day_of_month, frequency, first_due_on) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (profile_id, *fields))
            db().commit()
            return jsonify(id=cursor.lastrowid), 201
        except ValueError as error:
            return fail(str(error))


    @app.put("/api/bills/<int:item_id>")
    def update_bill(item_id):
        try:
            fields = bill_fields(payload())
            profile_id = current_profile()["id"]
            cursor = db().execute(
                "UPDATE bills SET name=?, category=?, amount_cents=?, day_of_month=?, frequency=?, first_due_on=? WHERE id=? AND profile_id=?",
                (*fields, item_id, profile_id))
            if not cursor.rowcount:
                return fail("Bill not found.", 404)
            category = remember_category(profile_id, fields[1])
            if category != fields[1]:
                db().execute("UPDATE bills SET category=? WHERE id=?", (category, item_id))
            db().commit()
            return jsonify(ok=True)
        except ValueError as error:
            return fail(str(error))


    @app.delete("/api/bills/<int:item_id>")
    def delete_bill(item_id):
        return delete_owned("bills", item_id)


    def bill_payment_candidates(profile_id, month):
        bills = [dict(row) for row in db().execute("""SELECT id, name, category,
            amount_cents, day_of_month, frequency, first_due_on FROM bills
            WHERE profile_id = ? ORDER BY name COLLATE NOCASE, id""", (profile_id,))]
        items, needs_schedule = [], []
        for bill in bills:
            if bill["frequency"] != "monthly" and not bill["first_due_on"]:
                needs_schedule.append({"id": bill["id"], "name": bill["name"],
                                       "frequency": bill["frequency"]})
                continue
            for due_on in bill_due_dates(bill, month):
                items.append({"bill_id": bill["id"], "name": bill["name"],
                              "category": bill["category"], "frequency": bill["frequency"],
                              "amount_cents": bill["amount_cents"], "due_on": due_on})
        items.sort(key=lambda item: (item["due_on"], item["name"].casefold(), item["bill_id"]))
        return items, needs_schedule


    @app.get("/api/bills/import-preview")
    def preview_bill_import():
        try:
            month = month_value(request.args.get("month", date.today().strftime("%Y-%m")))
        except ValueError as error:
            return fail(str(error))
        profile_id = current_profile()["id"]
        items, needs_schedule = bill_payment_candidates(profile_id, month)
        lower, upper, _ = month_span(month)
        imported = {(row["bill_id"], row["due_on"]) for row in db().execute("""
            SELECT bill_imports.bill_id, bill_imports.due_on FROM bill_imports
            JOIN bills ON bills.id = bill_imports.bill_id
            WHERE bills.profile_id = ? AND bill_imports.due_on >= ? AND bill_imports.due_on < ?""",
            (profile_id, lower, upper))}
        recorded = {(row["occurred_on"], row["amount_cents"], row["category"].casefold())
                    for row in db().execute("""SELECT occurred_on, amount_cents, category
                        FROM transactions WHERE profile_id = ? AND kind = 'expense'
                        AND occurred_on >= ? AND occurred_on < ?
                        AND id NOT IN (SELECT transaction_id FROM bill_imports)""",
                        (profile_id, lower, upper))}
        today = date.today().isoformat()
        for item in items:
            item["already_imported"] = (item["bill_id"], item["due_on"]) in imported
            item["possible_duplicate"] = (item["due_on"], item["amount_cents"],
                                          item["category"].casefold()) in recorded
            item["future"] = item["due_on"] > today
        return jsonify(month=month, today=today, items=items, needs_schedule=needs_schedule)


    @app.post("/api/bills/import")
    def import_bill_payments():
        try:
            data = payload()
            month = month_value(data.get("month"))
            selected = data.get("items")
            if not isinstance(selected, list) or not 1 <= len(selected) <= 500:
                raise ValueError("Select between 1 and 500 bill payments to import.")
            requests = []
            for item in selected:
                if not isinstance(item, dict) or isinstance(item.get("bill_id"), bool) or not isinstance(item.get("bill_id"), int) or item["bill_id"] <= 0:
                    raise ValueError("Choose valid bill payments from the preview.")
                due_on = iso_date(item.get("due_on"), "Payment date")
                if not due_on.startswith(f"{month}-") or due_on > date.today().isoformat():
                    raise ValueError("Choose payments due on or before today in the selected month.")
                requests.append((item["bill_id"], due_on))
            if len(set(requests)) != len(requests):
                raise ValueError("Choose each bill payment only once.")
            profile_id = current_profile()["id"]
            account_id = owned_account(db(), profile_id, data.get("account_id"), optional_default=True)
            conn = db()
            conn.execute("BEGIN IMMEDIATE")
            try:
                candidates, _ = bill_payment_candidates(profile_id, month)
                available = {(item["bill_id"], item["due_on"]): item for item in candidates}
                if any(key not in available for key in requests):
                    raise ValueError("A selected bill payment is no longer available. Refresh the preview.")
                imported_count = skipped_count = 0
                for key in requests:
                    bill_id, due_on = key
                    if conn.execute("SELECT 1 FROM bill_imports WHERE bill_id = ? AND due_on = ?",
                                    key).fetchone():
                        skipped_count += 1
                        continue
                    item = available[key]
                    cursor = conn.execute("""INSERT INTO transactions(profile_id, account_id, kind,
                        amount_cents, category, occurred_on, note)
                        VALUES(?, ?, 'expense', ?, ?, ?, ?)""",
                        (profile_id, account_id, item["amount_cents"], item["category"],
                         due_on, item["name"]))
                    conn.execute("INSERT INTO bill_imports(bill_id, due_on, transaction_id) VALUES(?, ?, ?)",
                                 (bill_id, due_on, cursor.lastrowid))
                    imported_count += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return jsonify(imported_count=imported_count, skipped_count=skipped_count), 201
        except ValueError as error:
            return fail(str(error))


    def commute_fields(data):
        mode = data.get("mode")
        if mode not in ("car", "public"):
            raise ValueError("Choose Car or Public transport.")
        raw_days = data.get("weekdays")
        if not isinstance(raw_days, list) or not raw_days or len(raw_days) > 7 or any(
                isinstance(day, bool) or str(day) not in {str(i) for i in range(7)}
                for day in raw_days):
            raise ValueError("Choose at least one commuting weekday.")
        days = sorted({int(day) for day in raw_days})
        region = data.get("bank_holiday_region", "none")
        if not isinstance(region, str) or region not in REGIONS:
            raise ValueError("Choose a valid UK bank holiday option.")
        leave_mode = data.get("leave_mode", "dates")
        if leave_mode not in ("dates", "annual"):
            raise ValueError("Choose annual leave days or exact dates.")
        leave_dates = data.get("excluded_dates", "")
        if leave_mode == "annual":
            raw_annual = data.get("annual_leave_days")
            if isinstance(raw_annual, bool) or not isinstance(raw_annual, (int, str)) or not re.fullmatch(r"\d{1,3}", str(raw_annual)):
                raise ValueError("Annual leave days must be a whole number from 0 to 365.")
            annual_days = int(raw_annual)
            if annual_days > 365:
                raise ValueError("Annual leave days must be a whole number from 0 to 365.")
            if not isinstance(leave_dates, str) or leave_dates.strip():
                raise ValueError("Use annual leave days or exact dates, not both.")
            leave_dates = ""
        else:
            parse_dates(leave_dates)
            annual_days = 0
            if data.get("annual_leave_days") not in (None, "", 0, "0"):
                raise ValueError("Use annual leave days or exact dates, not both.")
        if mode == "car":
            distance = positive_hundredths(data.get("distance"), "Daily round-trip distance", 500)
            mpg = positive_hundredths(data.get("mpg"), "UK miles per gallon", 200)
            fuel_price = money(data.get("fuel_price"), "Fuel price per litre")
            fare = 0
        else:
            distance = mpg = fuel_price = 0
            fare = money(data.get("fare"), "Daily return fare")
        return (clean_text(data.get("name"), "Commute name", 60), mode,
                distance, mpg, fuel_price, fare, ",".join(str(day) for day in days),
                leave_dates, region, leave_mode, annual_days)


    @app.post("/api/commutes/preview")
    def preview_commute():
        try:
            data = payload()
            month = month_value(data.get("month"))
            fields = commute_fields(data)
            keys = ("name", "mode", "distance_hundredths", "mpg_hundredths",
                    "fuel_price_cents", "fare_cents", "weekdays", "excluded_dates",
                    "bank_holiday_region", "leave_mode", "annual_leave_days")
            plan = dict(zip(keys, fields))
            holidays, error = (official_holidays() if plan["bank_holiday_region"] != "none"
                               else (None, None))
            return jsonify(commute_estimate(plan, month, holidays, error))
        except ValueError as error:
            return fail(str(error))


    @app.post("/api/commutes")
    def add_commute():
        try:
            fields = commute_fields(payload())
            cursor = db().execute("""INSERT INTO commutes(profile_id, name, mode,
                distance_hundredths, mpg_hundredths, fuel_price_cents, fare_cents,
                weekdays, excluded_dates, bank_holiday_region, leave_mode, annual_leave_days)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (current_profile()["id"], *fields))
            db().commit()
            return jsonify(id=cursor.lastrowid), 201
        except ValueError as error:
            return fail(str(error))


    @app.put("/api/commutes/<int:item_id>")
    def update_commute(item_id):
        try:
            fields = commute_fields(payload())
            cursor = db().execute("""UPDATE commutes SET name=?, mode=?,
                distance_hundredths=?, mpg_hundredths=?, fuel_price_cents=?, fare_cents=?,
                weekdays=?, excluded_dates=?, bank_holiday_region=?, leave_mode=?, annual_leave_days=?
                WHERE id=? AND profile_id=?""",
                (*fields, item_id, current_profile()["id"]))
            if not cursor.rowcount:
                return fail("Commute not found.", 404)
            db().commit()
            return jsonify(ok=True)
        except ValueError as error:
            return fail(str(error))


    @app.delete("/api/commutes/<int:item_id>")
    def delete_commute(item_id):
        return delete_owned("commutes", item_id)
