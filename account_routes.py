"""Account routes."""

def register(app, core):
    # Dependency binding avoids a second app instance when app.py runs as __main__.
    clean_text = core["clean_text"]
    ACCOUNT_KINDS = core["ACCOUNT_KINDS"]
    signed_money = core["signed_money"]
    jsonify = core["jsonify"]
    current_profile = core["current_profile"]
    account_balances = core["account_balances"]
    db = core["db"]
    date = core["date"]
    payload = core["payload"]
    fail = core["fail"]
    sqlite3 = core["sqlite3"]
    owned_account = core["owned_account"]
    iso_date = core["iso_date"]
    money = core["money"]

    def account_fields(data):
        name = clean_text(data.get("name"), "Account name", 40)
        kind = data.get("kind")
        if kind not in ACCOUNT_KINDS:
            raise ValueError("Choose Current, Savings, or Card account.")
        opening = signed_money(data.get("opening_balance", 0), "Opening balance")
        return name, kind, opening


    @app.get("/api/accounts")
    def list_accounts():
        profile_id = current_profile()["id"]
        return jsonify(accounts=account_balances(db(), profile_id),
                       balance_as_of=date.today().isoformat())


    @app.post("/api/accounts")
    def add_account():
        try:
            profile_id = current_profile()["id"]
            fields = account_fields(payload())
            if db().execute("SELECT COUNT(*) FROM accounts WHERE profile_id = ?", (profile_id,)).fetchone()[0] >= 20:
                raise ValueError("A profile can have up to 20 accounts.")
            cursor = db().execute("""INSERT INTO accounts(profile_id, name, kind,
                opening_balance_cents) VALUES(?, ?, ?, ?)""", (profile_id, *fields))
            db().commit()
            return jsonify(id=cursor.lastrowid), 201
        except sqlite3.IntegrityError:
            db().rollback()
            return fail("An account with that name already exists in this profile.", 409)
        except ValueError as error:
            return fail(str(error))


    @app.put("/api/accounts/<int:item_id>")
    def update_account(item_id):
        try:
            fields = account_fields(payload())
            cursor = db().execute("""UPDATE accounts SET name=?, kind=?, opening_balance_cents=?
                WHERE id=? AND profile_id=?""", (*fields, item_id, current_profile()["id"]))
            if not cursor.rowcount:
                return fail("Account not found.", 404)
            db().commit()
            return jsonify(ok=True)
        except sqlite3.IntegrityError:
            db().rollback()
            return fail("An account with that name already exists in this profile.", 409)
        except ValueError as error:
            return fail(str(error))


    @app.delete("/api/accounts/<int:item_id>")
    def delete_account(item_id):
        profile_id = current_profile()["id"]
        if not db().execute("SELECT 1 FROM accounts WHERE id=? AND profile_id=?",
                            (item_id, profile_id)).fetchone():
            return fail("Account not found.", 404)
        if db().execute("SELECT COUNT(*) FROM accounts WHERE profile_id=?",
                        (profile_id,)).fetchone()[0] <= 1:
            return fail("Keep at least one account in the profile.")
        if db().execute("SELECT 1 FROM transactions WHERE account_id=? LIMIT 1",
                        (item_id,)).fetchone() or db().execute("""SELECT 1 FROM transfers
                        WHERE source_account_id=? OR target_account_id=? LIMIT 1""",
                        (item_id, item_id)).fetchone():
            return fail("This account has transactions or transfers. Move or delete those entries before deleting it.")
        try:
            db().execute("DELETE FROM accounts WHERE id=? AND profile_id=?", (item_id, profile_id))
            db().commit()
            return jsonify(ok=True)
        except sqlite3.IntegrityError:
            db().rollback()
            return fail("This account is still used by ledger activity.")


    def transfer_fields(data, profile_id):
        source = owned_account(db(), profile_id, data.get("source_account_id"))
        target = owned_account(db(), profile_id, data.get("target_account_id"))
        if source == target:
            raise ValueError("Choose two different accounts for a transfer.")
        occurred_on = iso_date(data.get("occurred_on"), "Transfer date")
        if occurred_on > date.today().isoformat():
            raise ValueError("Transfers are for money already moved. Choose today or earlier.")
        note = data.get("note", "")
        if not isinstance(note, str) or len(note.strip()) > 200:
            raise ValueError("Transfer note must be at most 200 characters.")
        return source, target, money(data.get("amount"), "Transfer amount"), occurred_on, note.strip()


    @app.post("/api/transfers")
    def add_transfer():
        try:
            profile_id = current_profile()["id"]
            fields = transfer_fields(payload(), profile_id)
            cursor = db().execute("""INSERT INTO transfers(profile_id, source_account_id,
                target_account_id, amount_cents, occurred_on, note) VALUES(?, ?, ?, ?, ?, ?)""",
                (profile_id, *fields))
            db().commit()
            return jsonify(id=cursor.lastrowid), 201
        except ValueError as error:
            return fail(str(error))


    @app.put("/api/transfers/<int:item_id>")
    def update_transfer(item_id):
        try:
            profile_id = current_profile()["id"]
            fields = transfer_fields(payload(), profile_id)
            cursor = db().execute("""UPDATE transfers SET source_account_id=?, target_account_id=?,
                amount_cents=?, occurred_on=?, note=? WHERE id=? AND profile_id=?""",
                (*fields, item_id, profile_id))
            if not cursor.rowcount:
                return fail("Transfer not found.", 404)
            db().commit()
            return jsonify(ok=True)
        except ValueError as error:
            return fail(str(error))


    @app.delete("/api/transfers/<int:item_id>")
    def delete_transfer(item_id):
        cursor = db().execute("DELETE FROM transfers WHERE id=? AND profile_id=?",
                              (item_id, current_profile()["id"]))
        if not cursor.rowcount:
            return fail("Transfer not found.", 404)
        db().commit()
        return jsonify(ok=True)
