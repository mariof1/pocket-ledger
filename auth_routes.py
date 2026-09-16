"""Auth routes."""

from flask import Response

from ldap_auth import DirectoryRejected, DirectoryUnavailable


def save_directory_photo(connection, user_id, photo, mime):
    """Keep a photo in the owner's account and change its revision only when it changes."""
    existing = connection.execute(
        "SELECT photo, photo_mime FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if existing["photo"] == photo and existing["photo_mime"] == mime:
        return False
    connection.execute(
        """UPDATE users SET photo = ?, photo_mime = ?,
           photo_revision = photo_revision + 1 WHERE id = ?""",
        (photo, mime, user_id),
    )
    return True

def register_routes(app, core):
    # Bind the shared database and request helpers without importing app.py twice.
    session = core["session"]
    secrets = core["secrets"]
    current_user = core["current_user"]
    jsonify = core["jsonify"]
    db = core["db"]
    current_profile = core["current_profile"]
    destination_profile = core["destination_profile"]
    export_account = core["export_account"]
    date = core["date"]
    import_account = core["import_account"]
    payload = core["payload"]
    sqlite3 = core["sqlite3"]
    fail = core["fail"]
    re = core["re"]
    valid_password = core["valid_password"]
    generate_password_hash = core["generate_password_hash"]
    start_session = core["start_session"]
    request = core["request"]
    time = core["time"]
    check_password_hash = core["check_password_hash"]
    hashlib = core["hashlib"]
    clean_text = core["clean_text"]
    APP_VERSION = core["APP_VERSION"]
    ldap_settings = core["ldap_settings"]
    registration_enabled = core["registration_enabled"]
    authenticate_directory = core["authenticate_directory"]
    fetch_directory_photo = core["fetch_directory_photo"]
    logger = core["LOGGER"].getChild("auth")

    @app.get("/api/bootstrap")
    def bootstrap():
        directory_settings = ldap_settings()
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        user = current_user()
        if not user:
            return jsonify(csrf=session["csrf"], user=None, version=APP_VERSION,
                           auth={"ldap": directory_settings is not None,
                                 "registration": registration_enabled()})
        profiles = [dict(row) for row in db().execute(
            "SELECT id, name, currency FROM profiles WHERE user_id = ? ORDER BY id", (user["id"],)
        )]
        profile = current_profile()
        try:
            destination_profile(db(), user["id"])
            import_ready = True
        except ValueError:
            import_ready = False
        return jsonify(csrf=session["csrf"], user=dict(user), profiles=profiles, version=APP_VERSION,
                       profile_id=profile["id"] if profile else None,
                       import_ready=import_ready,
                       auth={"ldap": directory_settings is not None,
                             "registration": registration_enabled()})


    @app.get("/api/account/export")
    def download_account():
        document = export_account(db(), session["user_id"])
        response = jsonify(document)
        response.headers["Content-Disposition"] = (
            f'attachment; filename="pocket-ledger-{date.today().isoformat()}.json"')
        return response


    @app.get("/api/account/photo")
    def account_photo():
        photo = db().execute(
            "SELECT photo, photo_mime FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        if not photo or photo["photo"] is None or photo["photo_mime"] not in ("image/jpeg", "image/png"):
            return fail("No directory photo is available.", 404)
        return Response(photo["photo"], mimetype=photo["photo_mime"])


    @app.post("/api/account/photo/sync")
    def sync_account_photo():
        user = db().execute(
            "SELECT id, auth_source, directory_id FROM users WHERE id = ?", (session["user_id"],)
        ).fetchone()
        settings = ldap_settings()
        if not user or user["auth_source"] != "ldap" or not settings:
            return fail("Photo sync is available for directory accounts only.", 403)
        try:
            photo, mime = fetch_directory_photo(settings, user["directory_id"])
        except DirectoryRejected:
            return fail("Directory account was not found.", 404)
        except DirectoryUnavailable as error:
            return fail(str(error), 503)
        changed = save_directory_photo(db(), user["id"], photo, mime)
        if changed:
            db().commit()
        logger.info("directory_photo_sync user_id=%s available=%s changed=%s",
                    user["id"], photo is not None, changed)
        return jsonify(has_photo=photo is not None, changed=changed)


    @app.post("/api/account/import")
    def restore_account():
        try:
            result = import_account(db(), session["user_id"], payload())
            session["profile_id"] = result["profile_id"]
            return jsonify(profiles=result["profiles"], counts=result["counts"]), 201
        except sqlite3.IntegrityError:
            return fail("The export contains conflicting records. No data was imported.")
        except ValueError as error:
            return fail(str(error))


    @app.post("/api/register")
    def register():
        if not registration_enabled():
            return fail("New local accounts are disabled. Sign in with your directory account.", 403)
        data = payload()
        email = str(data.get("email", "")).strip().lower()
        password = data.get("password", "")
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) or len(email) > 254:
            return fail("Enter a valid email address.")
        if not valid_password(password):
            return fail("Password must be 12 to 128 characters.")
        try:
            cursor = db().execute("INSERT INTO users(email, password_hash) VALUES(?, ?)",
                                  (email, generate_password_hash(password)))
            user_id = cursor.lastrowid
            profile_id = db().execute("INSERT INTO profiles(user_id, name, currency) VALUES(?, 'Personal', 'GBP')",
                                      (user_id,)).lastrowid
            db().execute("""INSERT INTO accounts(profile_id, name, kind)
                VALUES(?, 'Current account', 'current')""", (profile_id,))
            db().commit()
        except sqlite3.IntegrityError:
            db().rollback()
            return fail("An account with that email already exists.", 409)
        start_session(user_id, profile_id)
        logger.info("registration_success user_id=%s remote=%s", user_id, request.remote_addr or "unknown")
        return jsonify(ok=True)


    @app.post("/api/login")
    def login():
        data = payload()
        identifier = str(data.get("email", data.get("username", ""))).strip()
        normalized = identifier.lower()
        password = data.get("password", "")
        directory_settings = ldap_settings()
        address = request.remote_addr or "unknown"
        attempt_key = f"email:{address}:{normalized[:254]}"
        address_key = f"ip:{address}"
        now = int(time.time())
        db().execute("DELETE FROM login_attempts WHERE first_at <= ?", (now - 15 * 60,))
        db().commit()
        attempt = db().execute("SELECT count FROM login_attempts WHERE key = ?", (attempt_key,)).fetchone()
        address_attempt = db().execute("SELECT count FROM login_attempts WHERE key = ?", (address_key,)).fetchone()
        if (attempt and attempt["count"] >= 5) or (address_attempt and address_attempt["count"] >= 30):
            logger.warning("login_rate_limited remote=%s scope=%s", address,
                           "account" if attempt and attempt["count"] >= 5 else "address")
            return fail("Too many sign-in attempts. Try again in 15 minutes.", 429)
        user = db().execute("SELECT * FROM users WHERE email = ? AND auth_source = 'local'",
                            (normalized,)).fetchone()
        local_accepted = (user is not None and isinstance(password, str)
                          and check_password_hash(user["password_hash"], password))
        if (not local_accepted and directory_settings is not None and isinstance(password, str)
                and 0 < len(identifier) <= 254 and 0 < len(password) <= 1024):
            try:
                directory_user = authenticate_directory(directory_settings, identifier, password)
            except DirectoryUnavailable as error:
                logger.warning("login_directory_unavailable remote=%s", address)
                return fail(str(error), 503)
            except DirectoryRejected as error:
                logger.info("login_directory_rejected remote=%s reason=%s", address,
                            {"Invalid username or password.": "credentials",
                             "This directory account is disabled.": "disabled",
                             "This directory account is locked.": "locked",
                             "This directory account is not permitted to use Pocket Ledger.": "group",
                             "Your directory account needs a valid email address.": "email"}
                            .get(str(error), "other"))
                directory_user = None
            if directory_user is not None:
                user = db().execute(
                    "SELECT * FROM users WHERE auth_source = 'ldap' AND directory_id = ?",
                    (directory_user.username,),
                ).fetchone()
                if user is None:
                    collision = db().execute("SELECT id FROM users WHERE email = ?",
                                             (directory_user.email,)).fetchone()
                    if collision:
                        logger.warning("login_directory_email_conflict remote=%s", address)
                        return fail("This directory email is already used by another account. Ask the server owner to resolve it.", 409)
                    try:
                        cursor = db().execute("""INSERT INTO users(
                            email, password_hash, auth_source, directory_id, display_name
                        ) VALUES(?, ?, 'ldap', ?, ?)""",
                            (directory_user.email, generate_password_hash(secrets.token_urlsafe(48)),
                             directory_user.username, directory_user.display_name))
                        user_id = cursor.lastrowid
                        profile_id = db().execute("""INSERT INTO profiles(user_id, name, currency)
                            VALUES(?, 'Personal', 'GBP')""", (user_id,)).lastrowid
                        db().execute("""INSERT INTO accounts(profile_id, name, kind)
                            VALUES(?, 'Current account', 'current')""", (profile_id,))
                        db().commit()
                        user = db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
                    except sqlite3.IntegrityError:
                        db().rollback()
                        user = db().execute(
                            "SELECT * FROM users WHERE auth_source = 'ldap' AND directory_id = ?",
                            (directory_user.username,),
                        ).fetchone()
                        if user is None:
                            logger.warning("login_directory_email_conflict remote=%s", address)
                            return fail("This directory email is already used by another account. Ask the server owner to resolve it.", 409)
                elif (user["email"] != directory_user.email
                      or user["display_name"] != directory_user.display_name):
                    collision = db().execute("SELECT id FROM users WHERE email = ? AND id != ?",
                                             (directory_user.email, user["id"])).fetchone()
                    if collision:
                        logger.warning("login_directory_email_conflict remote=%s", address)
                        return fail("This directory email is already used by another account. Ask the server owner to resolve it.", 409)
                    try:
                        db().execute("UPDATE users SET email = ?, display_name = ? WHERE id = ?",
                                     (directory_user.email, directory_user.display_name, user["id"]))
                        db().commit()
                    except sqlite3.IntegrityError:
                        db().rollback()
                        logger.warning("login_directory_email_conflict remote=%s", address)
                        return fail("This directory email is already used by another account. Ask the server owner to resolve it.", 409)
                    user = db().execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
                if save_directory_photo(db(), user["id"], directory_user.photo, directory_user.photo_mime):
                    db().commit()
        if not local_accepted and (directory_settings is None or user is None or user["auth_source"] != "ldap"):
            for key in (attempt_key, address_key):
                db().execute("""INSERT INTO login_attempts(key, count, first_at) VALUES(?, 1, ?)
                    ON CONFLICT(key) DO UPDATE SET count=count+1""", (key, now))
            db().commit()
            logger.info("login_failed remote=%s directory_enabled=%s", address,
                        directory_settings is not None)
            return fail("Email or password is incorrect.", 401)
        db().execute("DELETE FROM login_attempts WHERE key = ?", (attempt_key,))
        db().commit()
        profile = db().execute("SELECT id FROM profiles WHERE user_id = ? ORDER BY id LIMIT 1", (user["id"],)).fetchone()
        start_session(user["id"], profile["id"] if profile else None)
        logger.info("login_success user_id=%s source=%s remote=%s", user["id"],
                    user["auth_source"], address)
        return jsonify(ok=True)


    @app.post("/api/logout")
    def logout():
        user_id = session.get("user_id")
        token = session.get("auth_token")
        if isinstance(token, str):
            db().execute("DELETE FROM auth_sessions WHERE token_hash = ?",
                         (hashlib.sha256(token.encode()).hexdigest(),))
            db().commit()
        session.clear()
        logger.info("logout user_id=%s", user_id)
        return jsonify(ok=True)


    @app.post("/api/password")
    def change_password():
        data = payload()
        current = data.get("current_password")
        new = data.get("new_password")
        if not valid_password(new):
            return fail("New password must be 12 to 128 characters.")
        user_id = session["user_id"]
        user = db().execute("SELECT password_hash, auth_source FROM users WHERE id = ?", (user_id,)).fetchone()
        if user and user["auth_source"] != "local":
            return fail("Directory passwords are managed by Active Directory.")
        if not isinstance(current, str) or not user or not check_password_hash(user["password_hash"], current):
            return fail("Current password is incorrect.")
        if check_password_hash(user["password_hash"], new):
            return fail("Choose a different new password.")
        profile_id = current_profile()["id"]
        db().execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (generate_password_hash(new), user_id))
        db().execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        db().commit()
        start_session(user_id, profile_id)
        logger.info("password_changed user_id=%s sessions_revoked=true", user_id)
        return jsonify(ok=True)


    @app.post("/api/profiles")
    def add_profile():
        try:
            data = payload()
            name = clean_text(data.get("name"), "Profile name", 40)
            currency = data.get("currency", "GBP")
            if currency not in ("GBP", "EUR", "USD"):
                raise ValueError("Choose GBP, EUR, or USD.")
            if db().execute("SELECT COUNT(*) FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()[0] >= 10:
                raise ValueError("An account can have up to 10 profiles.")
            cursor = db().execute("INSERT INTO profiles(user_id, name, currency) VALUES(?, ?, ?)",
                                  (session["user_id"], name, currency))
            db().execute("""INSERT INTO accounts(profile_id, name, kind)
                VALUES(?, 'Current account', 'current')""", (cursor.lastrowid,))
            db().commit()
            session["profile_id"] = cursor.lastrowid
            return jsonify(id=cursor.lastrowid), 201
        except sqlite3.IntegrityError:
            return fail("A profile with that name already exists.", 409)
        except ValueError as error:
            return fail(str(error))


    @app.post("/api/profiles/<int:profile_id>/select")
    def select_profile(profile_id):
        row = db().execute("SELECT id FROM profiles WHERE id = ? AND user_id = ?",
                           (profile_id, session["user_id"])).fetchone()
        if not row:
            return fail("Profile not found.", 404)
        session["profile_id"] = profile_id
        return jsonify(ok=True)


    @app.delete("/api/profiles/<int:profile_id>")
    def delete_profile(profile_id):
        owned = db().execute("SELECT id FROM profiles WHERE id = ? AND user_id = ?",
                             (profile_id, session["user_id"])).fetchone()
        if not owned:
            return fail("Profile not found.", 404)
        if db().execute("SELECT COUNT(*) FROM profiles WHERE user_id = ?", (session["user_id"],)).fetchone()[0] <= 1:
            return fail("Keep at least one profile.")
        db().execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        db().commit()
        if session.get("profile_id") == profile_id:
            session.pop("profile_id", None)
            current_profile()
        return jsonify(ok=True)
