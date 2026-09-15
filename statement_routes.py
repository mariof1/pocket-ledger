"""Statement routes."""

def register(app, core):
    # Dependency binding avoids a second app instance when app.py runs as __main__.
    csv_table = core["csv_table"]
    hashlib = core["hashlib"]
    date = core["date"]
    db = core["db"]
    jsonify = core["jsonify"]
    payload = core["payload"]
    suggest_mapping = core["suggest_mapping"]
    fail = core["fail"]
    validate_mapping = core["validate_mapping"]
    current_profile = core["current_profile"]
    normalize_note = core["normalize_note"]
    statement_rows = core["statement_rows"]
    duplicate_for = core["duplicate_for"]
    owned_account = core["owned_account"]
    clean_text = core["clean_text"]
    transaction_fields = core["transaction_fields"]
    remember_category = core["remember_category"]
    sqlite3 = core["sqlite3"]

    def statement_context(data):
        text = data.get("text")
        headers, rows, delimiter = csv_table(text)
        return text, headers, rows, delimiter, hashlib.sha256(text.lstrip("\ufeff").encode("utf-8")).hexdigest()


    def statement_existing(profile_id, items):
        valid = [item["occurred_on"] for item in items if "occurred_on" in item]
        if not valid:
            return []
        from datetime import timedelta
        low = (date.fromisoformat(min(valid)) - timedelta(days=3)).isoformat() \
            if min(valid) > "0001-01-03" else date.min.isoformat()
        high = (date.fromisoformat(max(valid)) + timedelta(days=3)).isoformat() \
            if max(valid) < "9999-12-29" else date.max.isoformat()
        return [dict(row) for row in db().execute("""SELECT kind, amount_cents, category,
            occurred_on, note FROM transactions WHERE profile_id = ? AND occurred_on BETWEEN ? AND ?""",
            (profile_id, low, high))]


    @app.post("/api/statements/inspect")
    def inspect_statement():
        try:
            _, headers, rows, delimiter, _ = statement_context(payload())
            return jsonify(headers=headers, sample=rows[:3], delimiter=delimiter,
                           mapping=suggest_mapping(headers), row_count=len(rows))
        except ValueError as error:
            return fail(str(error))


    @app.post("/api/statements/preview")
    def preview_statement():
        try:
            data = payload()
            _, headers, rows, _, file_hash = statement_context(data)
            mapping = validate_mapping(data.get("mapping"), len(headers))
            profile_id = current_profile()["id"]
            known = {}
            for row in db().execute("""SELECT kind, note, category FROM transactions
                WHERE profile_id = ? AND note != '' ORDER BY occurred_on DESC, id DESC LIMIT 2000""",
                (profile_id,)):
                known.setdefault((row["kind"], normalize_note(row["note"])), row["category"])
            items = statement_rows(headers, rows, mapping, data.get("date_order", "dmy"),
                                   data.get("decimal_mark", "dot"),
                                   data.get("positive_expense", False), known)
            existing = statement_existing(profile_id, items)
            imported_rows = {row["source_row"] for row in db().execute("""SELECT source_row
                FROM statement_import_items WHERE profile_id = ? AND file_hash = ?""",
                (profile_id, file_hash))}
            reviewed = []
            for item in items:
                if item["row_number"] in imported_rows:
                    item["duplicate"] = "already imported from this file"
                elif "occurred_on" in item:
                    item["duplicate"] = duplicate_for(item, [*existing, *reviewed])
                if item.get("duplicate"):
                    item["include"] = False
                if "occurred_on" in item:
                    reviewed.append(item)
            return jsonify(rows=items, row_count=len(rows), file_hash=file_hash,
                           profile_id=profile_id,
                           already_imported=len(imported_rows))
        except ValueError as error:
            return fail(str(error))


    @app.get("/api/statements/history")
    def statement_history():
        profile_id = current_profile()["id"]
        batches = [dict(row) for row in db().execute("""SELECT id, filename, imported_count,
            skipped_count, created_at FROM statement_imports WHERE profile_id = ?
            ORDER BY id DESC LIMIT 20""", (profile_id,))]
        return jsonify(batches=batches)


    @app.post("/api/statements/save")
    def save_statement():
        try:
            data = payload()
            profile_id = current_profile()["id"]
            if isinstance(data.get("profile_id"), bool) or data.get("profile_id") != profile_id:
                raise ValueError("The active profile changed since the statement preview. Review the file again.")
            account_id = owned_account(db(), profile_id, data.get("account_id"), optional_default=True)
            _, _, source_rows, _, file_hash = statement_context(data)
            filename = clean_text(data.get("filename"), "Statement filename", 120)
            selected = data.get("rows")
            if not isinstance(selected, list) or not 1 <= len(selected) <= len(source_rows):
                raise ValueError("Select at least one valid statement row to import.")
            requested = []
            for item in selected:
                if not isinstance(item, dict) or isinstance(item.get("row_number"), bool) or \
                        not isinstance(item.get("row_number"), int) or \
                        not 2 <= item["row_number"] <= len(source_rows) + 1:
                    raise ValueError("A selected row does not belong to this statement.")
                try:
                    fields = transaction_fields(item)
                except ValueError as error:
                    raise ValueError(f"Row {item['row_number']}: {error}") from error
                if not isinstance(item.get("allow_duplicate"), bool):
                    raise ValueError("Review duplicate warnings before saving.")
                requested.append((item["row_number"], fields, item["allow_duplicate"]))
            if len({item[0] for item in requested}) != len(requested):
                raise ValueError("Select each statement row only once.")
            conn = db()
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing_imports = {row["source_row"] for row in conn.execute("""SELECT source_row
                    FROM statement_import_items WHERE profile_id = ? AND file_hash = ?""",
                    (profile_id, file_hash))}
                if any(row_number in existing_imports for row_number, _, _ in requested):
                    raise ValueError("A selected row was already imported from this file. Refresh the preview.")
                provisional = []
                existing = statement_existing(profile_id, [{"occurred_on": fields[3]}
                                                           for _, fields, _ in requested])
                for row_number, fields, allow_duplicate in requested:
                    kind, amount_cents, category, occurred_on, note = fields
                    candidate = dict(kind=kind, amount_cents=amount_cents, category=category,
                                     occurred_on=occurred_on, note=note)
                    duplicate = duplicate_for(candidate, [*existing, *provisional])
                    if duplicate and not allow_duplicate:
                        raise ValueError(f"Row {row_number} looks like a {duplicate} duplicate. Review it again or explicitly allow the duplicate.")
                    provisional.append(candidate)
                cursor = conn.execute("""INSERT INTO statement_imports(profile_id, filename,
                    file_hash, imported_count, skipped_count) VALUES(?, ?, ?, ?, ?)""",
                    (profile_id, filename, file_hash, len(requested), len(source_rows) - len(requested)))
                batch_id = cursor.lastrowid
                for (row_number, fields, _), candidate in zip(requested, provisional):
                    category = remember_category(profile_id, candidate["category"])
                    tx = conn.execute("""INSERT INTO transactions(profile_id, account_id, kind,
                        amount_cents, category, occurred_on, note) VALUES(?, ?, ?, ?, ?, ?, ?)""",
                        (profile_id, account_id, fields[0], fields[1], category, fields[3], fields[4]))
                    conn.execute("""INSERT INTO statement_import_items(batch_id, profile_id,
                        file_hash, source_row, transaction_id) VALUES(?, ?, ?, ?, ?)""",
                        (batch_id, profile_id, file_hash, row_number, tx.lastrowid))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return jsonify(imported_count=len(requested), skipped_count=len(source_rows) - len(requested),
                           batch_id=batch_id), 201
        except sqlite3.IntegrityError:
            return fail("The statement conflicts with existing data. No rows were imported.")
        except ValueError as error:
            return fail(str(error))
