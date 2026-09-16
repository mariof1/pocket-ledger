"""LDAP configuration and sign-in integration tests."""

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

TEST_DIR = tempfile.TemporaryDirectory()
os.environ["LEDGER_INSTANCE"] = TEST_DIR.name
os.environ.setdefault("LEDGER_ACCESS_LOG", "0")

import app as app_module
from app import app, db
from ldap3.core.exceptions import LDAPException
from ldap_auth import (DirectoryRejected, DirectoryUnavailable, DirectoryUser, LdapSettings,
                       _photo_from_entry, authenticate, fetch_photo, settings_from_env)


JPEG_PHOTO = b"\xff\xd8\xff" + b"profile picture" + b"\xff\xd9"
NEW_JPEG_PHOTO = b"\xff\xd8\xff" + b"new profile picture" + b"\xff\xd9"


class LdapConfigurationTests(unittest.TestCase):
    def test_directory_failure_logs_stage_and_reason_without_exception_contents(self):
        settings = LdapSettings(
            url="ldaps://dc.example.com", base_dn="DC=example,DC=com",
            bind_dn="CN=svc,DC=example,DC=com", bind_password="private-bind-secret",
            required_group=None, ca_cert=None, verify_tls=True, start_tls=False,
        )
        with patch("ldap_auth._server", return_value=(object(), object())), \
             patch("ldap_auth.Connection", side_effect=LDAPException(
                 "certificate verify failed private-bind-secret")), \
             self.assertLogs("pocket_ledger.ldap", level="WARNING") as captured:
            with self.assertRaises(DirectoryUnavailable):
                authenticate(settings, "private-username", "private-password")
        line = captured.output[0]
        self.assertIn("operation=login stage=service_bind reason=certificate_verification", line)
        for private in ("private-bind-secret", "private-username", "private-password"):
            self.assertNotIn(private, line)

    def test_photo_prefers_thumbnail_and_rejects_unsafe_or_oversized_data(self):
        entry = SimpleNamespace(
            thumbnailPhoto=SimpleNamespace(value=JPEG_PHOTO),
            jpegPhoto=SimpleNamespace(value=NEW_JPEG_PHOTO),
        )
        self.assertEqual(_photo_from_entry(entry), (JPEG_PHOTO, "image/jpeg"))
        entry.thumbnailPhoto.value = b"<svg><script>alert(1)</script></svg>"
        self.assertEqual(_photo_from_entry(entry), (NEW_JPEG_PHOTO, "image/jpeg"))
        entry.jpegPhoto.value = b"\xff\xd8\xff" + b"x" * 1_000_000 + b"\xff\xd9"
        self.assertEqual(_photo_from_entry(entry), (None, None))

    def test_photo_refresh_uses_service_bind_and_escaped_username(self):
        settings = LdapSettings(
            url="ldaps://dc.example.com", base_dn="DC=example,DC=com",
            bind_dn="CN=svc,DC=example,DC=com", bind_password="bind-secret",
            required_group=None, ca_cert=None, verify_tls=True, start_tls=False,
        )
        entry = SimpleNamespace(thumbnailPhoto=SimpleNamespace(value=JPEG_PHOTO))
        captured = {}
        def search(_base, ldap_filter, **kwargs):
            captured["filter"] = ldap_filter
            captured["attributes"] = kwargs["attributes"]
            return True
        service = SimpleNamespace(entries=[entry], search=search, unbind=lambda: None)
        with patch("ldap_auth._server", return_value=(object(), object())), \
             patch("ldap_auth.Connection", return_value=service) as connection:
            self.assertEqual(fetch_photo(settings, "mario*)(objectClass=*)"),
                             (JPEG_PHOTO, "image/jpeg"))
        self.assertIn(r"mario\2a\29\28objectClass=\2a\29", captured["filter"])
        self.assertEqual(captured["attributes"], ["thumbnailPhoto", "jpegPhoto"])
        self.assertEqual(connection.call_args.kwargs["user"], settings.bind_dn)

    def test_configuration_requires_service_bind_values_and_supports_secret_file(self):
        with self.assertRaisesRegex(RuntimeError, "missing"):
            settings_from_env({"LEDGER_LDAP_URL": "ldaps://dc.example.com"})
        settings = settings_from_env({
            "LEDGER_LDAP_URL": "ldaps://dc.example.com:636",
            "LEDGER_LDAP_BASE_DN": "OU=Users,DC=example,DC=com",
            "LEDGER_LDAP_BIND_DN": "CN=svc,OU=Service Accounts,DC=example,DC=com",
            "LEDGER_LDAP_BIND_PASSWORD": "secret",
            "LEDGER_LDAP_REQUIRED_GROUP": "CN=Ledger,OU=Groups,DC=example,DC=com",
        })
        self.assertEqual(settings.base_dn, "OU=Users,DC=example,DC=com")
        self.assertTrue(settings.verify_tls)
        self.assertFalse(settings.start_tls)

    def test_configuration_rejects_invalid_urls_and_ldaps_starttls(self):
        base = {
            "LEDGER_LDAP_BASE_DN": "DC=example,DC=com",
            "LEDGER_LDAP_BIND_DN": "CN=svc,DC=example,DC=com",
            "LEDGER_LDAP_BIND_PASSWORD": "secret",
        }
        with self.assertRaisesRegex(RuntimeError, "ldap:// or ldaps://"):
            settings_from_env({**base, "LEDGER_LDAP_URL": "https://dc.example.com"})
        with self.assertRaisesRegex(RuntimeError, "START_TLS"):
            settings_from_env({**base, "LEDGER_LDAP_URL": "ldaps://dc.example.com",
                               "LEDGER_LDAP_START_TLS": "1"})
        with self.assertRaisesRegex(RuntimeError, "ALLOW_INSECURE"):
            settings_from_env({**base, "LEDGER_LDAP_URL": "ldap://dc.example.com"})
        settings = settings_from_env({**base, "LEDGER_LDAP_URL": "ldap://dc.example.com",
                                      "LEDGER_LDAP_START_TLS": "1"})
        self.assertTrue(settings.start_tls)

    def test_authentication_escapes_search_input_and_binds_as_the_found_user(self):
        settings = LdapSettings(
            url="ldaps://dc.example.com", base_dn="DC=example,DC=com",
            bind_dn="CN=svc,DC=example,DC=com", bind_password="bind-secret",
            required_group="CN=Ledger,OU=Groups,DC=example,DC=com",
            ca_cert=None, verify_tls=True, start_tls=False,
        )
        entry = SimpleNamespace(
            entry_dn="CN=Mario,OU=Users,DC=example,DC=com",
            sAMAccountName=SimpleNamespace(value="Mario"),
            userPrincipalName=SimpleNamespace(value="mario@example.com"),
            mail=SimpleNamespace(value="mario@example.com"),
            displayName=SimpleNamespace(value="Mario Example"),
            userAccountControl=SimpleNamespace(value=512),
            lockoutTime=SimpleNamespace(value=0),
            memberOf=SimpleNamespace(values=["CN=Ledger,OU=Groups,DC=example,DC=com"]),
            thumbnailPhoto=SimpleNamespace(value=JPEG_PHOTO),
        )
        service = SimpleNamespace(entries=[entry], search=lambda *_args, **_kwargs: True,
                                  unbind=lambda: None)
        user_bind = SimpleNamespace(unbind=lambda: None)
        connections = []

        def connection(_server, **kwargs):
            connections.append(kwargs)
            return service if len(connections) == 1 else user_bind

        captured = {}
        def search(_base, ldap_filter, **_kwargs):
            captured["filter"] = ldap_filter
            return True
        service.search = search
        with patch("ldap_auth._server", return_value=(object(), object())), \
             patch("ldap_auth.Connection", side_effect=connection):
            user = authenticate(settings, "mario*)(objectClass=*)", "user-secret")
        self.assertEqual(user.email, "mario@example.com")
        self.assertEqual((user.photo, user.photo_mime), (JPEG_PHOTO, "image/jpeg"))
        self.assertIn(r"mario\2a\29\28objectClass=\2a\29", captured["filter"])
        self.assertEqual(connections[0]["user"], settings.bind_dn)
        self.assertEqual(connections[1]["user"], entry.entry_dn)
        self.assertEqual(connections[1]["password"], "user-secret")

    def test_required_group_is_enforced_before_user_password_bind(self):
        settings = LdapSettings(
            url="ldaps://dc.example.com", base_dn="DC=example,DC=com",
            bind_dn="CN=svc,DC=example,DC=com", bind_password="bind-secret",
            required_group="CN=Ledger,DC=example,DC=com", ca_cert=None,
            verify_tls=True, start_tls=False,
        )
        entry = SimpleNamespace(
            entry_dn="CN=Other,DC=example,DC=com",
            sAMAccountName=SimpleNamespace(value="other"),
            userPrincipalName=SimpleNamespace(value="other@example.com"),
            mail=SimpleNamespace(value="other@example.com"),
            displayName=SimpleNamespace(value="Other User"),
            userAccountControl=SimpleNamespace(value=512), lockoutTime=SimpleNamespace(value=0),
            memberOf=SimpleNamespace(values=[]),
        )
        service = SimpleNamespace(entries=[entry], search=lambda *_args, **_kwargs: True,
                                  unbind=lambda: None)
        with patch("ldap_auth._server", return_value=(object(), object())), \
             patch("ldap_auth.Connection", return_value=service) as connection:
            with self.assertRaisesRegex(DirectoryRejected, "not permitted"):
                authenticate(settings, "other", "user-secret")
        connection.assert_called_once()

    def test_historical_lockout_time_does_not_block_an_unlocked_account(self):
        settings = LdapSettings(
            url="ldaps://dc.example.com", base_dn="DC=example,DC=com",
            bind_dn="CN=svc,DC=example,DC=com", bind_password="bind-secret",
            required_group=None, ca_cert=None, verify_tls=True, start_tls=False,
        )
        entry = SimpleNamespace(
            entry_dn="CN=Mario,OU=Users,DC=example,DC=com",
            sAMAccountName=SimpleNamespace(value="Mario"),
            userPrincipalName=SimpleNamespace(value="mario@example.com"),
            mail=SimpleNamespace(value="mario@example.com"),
            displayName=SimpleNamespace(value="Mario Example"),
            userAccountControl=SimpleNamespace(value=512),
            lockoutTime=SimpleNamespace(value=133000000000000000),
            memberOf=SimpleNamespace(values=[]),
        )
        setattr(entry, "msDS-User-Account-Control-Computed", SimpleNamespace(value=0))
        service = SimpleNamespace(entries=[entry], search=lambda *_args, **_kwargs: True,
                                  unbind=lambda: None)
        user_bind = SimpleNamespace(unbind=lambda: None)
        with patch("ldap_auth._server", return_value=(object(), object())), \
             patch("ldap_auth.Connection", side_effect=[service, user_bind]) as connection:
            user = authenticate(settings, "mario", "user-secret")
        self.assertEqual(user.username, "mario")
        self.assertEqual(connection.call_count, 2)

    def test_current_ad_lockout_flag_blocks_user_bind(self):
        settings = LdapSettings(
            url="ldaps://dc.example.com", base_dn="DC=example,DC=com",
            bind_dn="CN=svc,DC=example,DC=com", bind_password="bind-secret",
            required_group=None, ca_cert=None, verify_tls=True, start_tls=False,
        )
        entry = SimpleNamespace(
            entry_dn="CN=Mario,OU=Users,DC=example,DC=com",
            sAMAccountName=SimpleNamespace(value="Mario"),
            userPrincipalName=SimpleNamespace(value="mario@example.com"),
            mail=SimpleNamespace(value="mario@example.com"),
            displayName=SimpleNamespace(value="Mario Example"),
            userAccountControl=SimpleNamespace(value=512),
            memberOf=SimpleNamespace(values=[]),
        )
        setattr(entry, "msDS-User-Account-Control-Computed", SimpleNamespace(value=0x10))
        service = SimpleNamespace(entries=[entry], search=lambda *_args, **_kwargs: True,
                                  unbind=lambda: None)
        with patch("ldap_auth._server", return_value=(object(), object())), \
             patch("ldap_auth.Connection", return_value=service) as connection:
            with self.assertRaisesRegex(DirectoryRejected, "locked"):
                authenticate(settings, "mario", "user-secret")
        connection.assert_called_once()


class LdapLoginTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        self.settings = object()
        self.directory_user = DirectoryUser(
            username="mario", email="mario@example.com", display_name="Mario Example")

    def request(self, path, data):
        return self.client.post(path, json=data, headers={"X-CSRF-Token": self.csrf})

    def test_first_directory_login_provisions_account_and_password_is_managed_by_ad(self):
        with patch.object(app_module, "LDAP_SETTINGS", self.settings), \
             patch.object(app_module, "_authenticate_directory", return_value=self.directory_user):
            response = self.request("/api/login", {"email": "mario", "password": "directory password"})
            self.assertEqual(response.status_code, 200, response.json)
            bootstrap = self.client.get("/api/bootstrap").json
            self.assertEqual(bootstrap["user"]["auth_source"], "ldap")
            self.assertEqual(bootstrap["user"]["display_name"], "Mario Example")
            self.assertEqual(len(bootstrap["profiles"]), 1)
            self.csrf = bootstrap["csrf"]
            changed = self.request("/api/password", {
                "current_password": "directory password", "new_password": "a different long password"
            })
            self.assertEqual(changed.status_code, 400)
            self.assertIn("Active Directory", changed.json["error"])
            with app.app_context():
                saved = db().execute("""SELECT email, directory_id FROM users
                    WHERE auth_source='ldap' AND directory_id='mario'""").fetchone()
                self.assertEqual(tuple(saved), ("mario@example.com", "mario"))

    def test_directory_outage_returns_service_unavailable_without_provisioning(self):
        with patch.object(app_module, "LDAP_SETTINGS", self.settings), \
             patch.object(app_module, "_authenticate_directory",
                          side_effect=DirectoryUnavailable("Directory authentication is temporarily unavailable.")):
            response = self.request("/api/login", {"email": "unavailable", "password": "password"})
            self.assertEqual(response.status_code, 503)
            with app.app_context():
                self.assertIsNone(db().execute(
                    "SELECT id FROM users WHERE directory_id='unavailable'").fetchone())

    def test_directory_login_does_not_merge_with_an_existing_local_account(self):
        local_email = "ldap-collision@example.com"
        registered = self.request("/api/register", {
            "email": local_email, "password": "a strong local password"
        })
        self.assertEqual(registered.status_code, 200)
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        self.assertEqual(self.request("/api/logout", {}).status_code, 200)
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        directory_user = DirectoryUser(username="collision", email=local_email,
                                       display_name="Directory Collision")
        with patch.object(app_module, "LDAP_SETTINGS", self.settings), \
             patch.object(app_module, "_authenticate_directory", return_value=directory_user):
            response = self.request("/api/login", {
                "email": "collision", "password": "directory password"
            })
        self.assertEqual(response.status_code, 409)
        with app.app_context():
            saved = db().execute("SELECT auth_source, directory_id FROM users WHERE email = ?",
                                 (local_email,)).fetchone()
            self.assertEqual(tuple(saved), ("local", None))

    def test_directory_photo_sync_serves_only_the_current_account(self):
        directory_user = DirectoryUser(
            username="picture.user", email="picture-user@example.com",
            display_name="Picture User", photo=JPEG_PHOTO, photo_mime="image/jpeg",
        )
        with patch.object(app_module, "LDAP_SETTINGS", self.settings), \
             patch.object(app_module, "_authenticate_directory", return_value=directory_user):
            self.assertEqual(self.request("/api/login", {
                "email": "picture.user", "password": "directory password"
            }).status_code, 200)
        bootstrap = self.client.get("/api/bootstrap").json
        self.assertEqual(bootstrap["user"]["has_photo"], 1)
        self.assertNotIn("photo", bootstrap["user"])
        first_revision = bootstrap["user"]["photo_revision"]
        response = self.client.get("/api/account/photo")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, JPEG_PHOTO)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

        self.csrf = bootstrap["csrf"]
        with patch.object(app_module, "LDAP_SETTINGS", self.settings), \
             patch.object(app_module, "_fetch_directory_photo",
                          return_value=(NEW_JPEG_PHOTO, "image/jpeg")):
            refreshed = self.request("/api/account/photo/sync", {})
        self.assertEqual(refreshed.status_code, 200)
        self.assertEqual(refreshed.json, {"has_photo": True, "changed": True})
        self.assertEqual(self.client.get("/api/account/photo").data, NEW_JPEG_PHOTO)
        self.assertGreater(self.client.get("/api/bootstrap").json["user"]["photo_revision"], first_revision)

        with patch.object(app_module, "LDAP_SETTINGS", self.settings), \
             patch.object(app_module, "_fetch_directory_photo",
                          side_effect=DirectoryUnavailable("Directory authentication is temporarily unavailable.")):
            self.assertEqual(self.request("/api/account/photo/sync", {}).status_code, 503)
        self.assertEqual(self.client.get("/api/account/photo").data, NEW_JPEG_PHOTO)

        with patch.object(app_module, "LDAP_SETTINGS", self.settings), \
             patch.object(app_module, "_fetch_directory_photo", return_value=(None, None)):
            self.assertEqual(self.request("/api/account/photo/sync", {}).json,
                             {"has_photo": False, "changed": True})
        self.assertEqual(self.client.get("/api/account/photo").status_code, 404)
        self.assertEqual(self.client.get("/api/bootstrap").json["user"]["has_photo"], 0)

        self.assertEqual(self.request("/api/logout", {}).status_code, 200)
        self.assertEqual(self.client.get("/api/account/photo").status_code, 401)

    def test_local_account_cannot_sync_a_directory_photo(self):
        email = "local-photo-test@example.com"
        self.assertEqual(self.request("/api/register", {
            "email": email, "password": "a strong password 123"
        }).status_code, 200)
        self.csrf = self.client.get("/api/bootstrap").json["csrf"]
        self.assertEqual(self.request("/api/account/photo/sync", {}).status_code, 403)
        self.assertEqual(self.client.get("/api/account/photo").status_code, 404)

    def test_registration_can_be_disabled_while_directory_login_remains_available(self):
        with patch.object(app_module, "REGISTRATION_ENABLED", False):
            self.assertFalse(self.client.get("/api/bootstrap").json["auth"]["registration"])
            response = self.request("/api/register", {
                "email": "blocked@example.com", "password": "a strong password 123"
            })
            self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
