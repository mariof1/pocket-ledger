"""Optional Active Directory authentication through LDAP."""

from __future__ import annotations

import os
import logging
import re
import ssl
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from ldap3 import AUTO_BIND_NO_TLS, AUTO_BIND_TLS_BEFORE_BIND, Connection, Server, SUBTREE, Tls
from ldap3.core.exceptions import LDAPBindError, LDAPException, LDAPInvalidCredentialsResult
from ldap3.utils.conv import escape_filter_chars
from ledger_logging import ldap_failure


logger = logging.getLogger("pocket_ledger.ldap")


class DirectoryRejected(Exception):
    """The directory was reached, but the supplied identity cannot sign in."""


class DirectoryUnavailable(Exception):
    """The configured directory could not complete authentication."""


@dataclass(frozen=True)
class LdapSettings:
    url: str
    base_dn: str
    bind_dn: str
    bind_password: str
    required_group: str | None
    ca_cert: str | None
    verify_tls: bool
    start_tls: bool
    timeout: int = 10


@dataclass(frozen=True)
class DirectoryUser:
    username: str
    email: str
    display_name: str
    photo: bytes | None = None
    photo_mime: str | None = None


MAX_PHOTO_BYTES = 1_000_000


def _photo_from_entry(entry) -> tuple[bytes | None, str | None]:
    """Use only small browser-safe image formats from AD's binary photo attributes."""
    for attribute in ("thumbnailPhoto", "jpegPhoto"):
        value = _attribute(entry, attribute, None)
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if not isinstance(value, bytes) or not 0 < len(value) <= MAX_PHOTO_BYTES:
            continue
        if value.startswith(b"\xff\xd8\xff") and value.endswith(b"\xff\xd9"):
            return value, "image/jpeg"
        if value.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in value[-32:]:
            return value, "image/png"
    return None, None


def _boolean(name: str, default: bool, environment) -> bool:
    value = environment.get(name)
    if value is None:
        return default
    if value.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if value.strip().lower() in ("0", "false", "no", "off"):
        return False
    raise RuntimeError(f"{name} must be 1 or 0.")


def _password(environment) -> str:
    value = environment.get("LEDGER_LDAP_BIND_PASSWORD")
    filename = environment.get("LEDGER_LDAP_BIND_PASSWORD_FILE")
    if value and filename:
        raise RuntimeError("Set only one of LEDGER_LDAP_BIND_PASSWORD or LEDGER_LDAP_BIND_PASSWORD_FILE.")
    if filename:
        try:
            value = Path(filename).read_text(encoding="utf-8").rstrip("\r\n")
        except OSError as error:
            raise RuntimeError("Unable to read LEDGER_LDAP_BIND_PASSWORD_FILE.") from error
    return value or ""


def settings_from_env(environment=None) -> LdapSettings | None:
    environment = os.environ if environment is None else environment
    url = environment.get("LEDGER_LDAP_URL", "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if (parsed.scheme not in ("ldap", "ldaps") or not parsed.hostname
            or parsed.path not in ("", "/") or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise RuntimeError("LEDGER_LDAP_URL must be an ldap:// or ldaps:// server URL.")
    required = {
        "LEDGER_LDAP_BASE_DN": environment.get("LEDGER_LDAP_BASE_DN", "").strip(),
        "LEDGER_LDAP_BIND_DN": environment.get("LEDGER_LDAP_BIND_DN", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    password = _password(environment)
    if not password:
        missing.append("LEDGER_LDAP_BIND_PASSWORD or LEDGER_LDAP_BIND_PASSWORD_FILE")
    if missing:
        raise RuntimeError("LDAP is enabled but these settings are missing: " + ", ".join(missing))
    start_tls = _boolean("LEDGER_LDAP_START_TLS", False, environment)
    if parsed.scheme == "ldaps" and start_tls:
        raise RuntimeError("LEDGER_LDAP_START_TLS cannot be used with an ldaps:// URL.")
    if (parsed.scheme == "ldap" and not start_tls
            and not _boolean("LEDGER_LDAP_ALLOW_INSECURE", False, environment)):
        raise RuntimeError("An ldap:// URL requires LEDGER_LDAP_START_TLS=1 or an explicit LEDGER_LDAP_ALLOW_INSECURE=1.")
    return LdapSettings(
        url=url,
        base_dn=required["LEDGER_LDAP_BASE_DN"],
        bind_dn=required["LEDGER_LDAP_BIND_DN"],
        bind_password=password,
        required_group=environment.get("LEDGER_LDAP_REQUIRED_GROUP", "").strip() or None,
        ca_cert=environment.get("LEDGER_LDAP_CA_CERT", "").strip() or None,
        verify_tls=_boolean("LEDGER_LDAP_TLS_VERIFY", True, environment),
        start_tls=start_tls,
    )


def _server(settings: LdapSettings) -> tuple[Server, object]:
    parsed = urlparse(settings.url)
    use_ssl = parsed.scheme == "ldaps"
    tls = Tls(
        validate=ssl.CERT_REQUIRED if settings.verify_tls else ssl.CERT_NONE,
        ca_certs_file=settings.ca_cert,
    )
    server = Server(parsed.hostname, port=parsed.port or (636 if use_ssl else 389),
                    use_ssl=use_ssl, tls=tls, connect_timeout=settings.timeout)
    auto_bind = AUTO_BIND_TLS_BEFORE_BIND if settings.start_tls else AUTO_BIND_NO_TLS
    return server, auto_bind


def _attribute(entry, name, default=""):
    value = getattr(entry, name, None)
    if value is None:
        return default
    return value.value if value.value is not None else default


def authenticate(settings: LdapSettings, identifier: str, password: str) -> DirectoryUser:
    """Find an AD user with a service bind, then verify credentials with a user bind."""
    identifier = identifier.strip()
    if not identifier or not password:
        raise DirectoryRejected("Invalid username or password.")
    stage = "server_setup"
    service = None
    try:
        server, auto_bind = _server(settings)
        stage = "service_bind"
        service = Connection(server, user=settings.bind_dn, password=settings.bind_password,
                             auto_bind=auto_bind, receive_timeout=settings.timeout,
                             raise_exceptions=True)
        stage = "user_search"
        escaped = escape_filter_chars(identifier)
        found = service.search(
            settings.base_dn,
            "(&(objectClass=user)(objectCategory=person)"
            f"(|(sAMAccountName={escaped})(userPrincipalName={escaped})))",
            search_scope=SUBTREE,
            attributes=["sAMAccountName", "userPrincipalName", "mail", "displayName",
                        "userAccountControl", "msDS-User-Account-Control-Computed", "memberOf",
                        "thumbnailPhoto", "jpegPhoto"],
            size_limit=2,
            time_limit=settings.timeout,
        )
        if not found or len(service.entries) != 1:
            raise DirectoryRejected("Invalid username or password.")
        entry = service.entries[0]
        account_control = int(_attribute(entry, "userAccountControl", 0) or 0)
        if account_control & 0x0002:
            raise DirectoryRejected("This directory account is disabled.")
        computed_control = int(_attribute(
            entry, "msDS-User-Account-Control-Computed", 0) or 0)
        if computed_control & 0x0010:
            raise DirectoryRejected("This directory account is locked.")
        groups = getattr(entry, "memberOf", None)
        group_values = groups.values if groups is not None else []
        if settings.required_group and not any(
                str(group).casefold() == settings.required_group.casefold() for group in group_values):
            raise DirectoryRejected("This directory account is not permitted to use Pocket Ledger.")
        username = str(_attribute(entry, "sAMAccountName")).strip()
        upn = str(_attribute(entry, "userPrincipalName")).strip().lower()
        email = str(_attribute(entry, "mail")).strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            email = upn if re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", upn) else ""
        if not username or not email or len(email) > 254:
            raise DirectoryRejected("Your directory account needs a valid email address.")
        user_connection = None
        try:
            stage = "user_bind"
            user_connection = Connection(server, user=entry.entry_dn, password=password,
                                         auto_bind=auto_bind, receive_timeout=settings.timeout,
                                         raise_exceptions=True)
        except (LDAPInvalidCredentialsResult, LDAPBindError) as error:
            raise DirectoryRejected("Invalid username or password.") from error
        finally:
            if user_connection is not None:
                user_connection.unbind()
        photo, photo_mime = _photo_from_entry(entry)
        return DirectoryUser(username=username.lower(), email=email,
                             display_name=str(_attribute(entry, "displayName")).strip(),
                             photo=photo, photo_mime=photo_mime)
    except DirectoryRejected:
        raise
    except (LDAPException, OSError) as error:
        ldap_failure(logger, "login", stage, error)
        raise DirectoryUnavailable("Directory authentication is temporarily unavailable.") from error
    finally:
        if service is not None:
            service.unbind()


def fetch_photo(settings: LdapSettings, username: str) -> tuple[bytes | None, str | None]:
    """Refresh a signed-in directory user's photo using the configured service bind."""
    if not username:
        raise DirectoryRejected("Directory identity is missing.")
    stage = "server_setup"
    service = None
    try:
        server, auto_bind = _server(settings)
        stage = "service_bind"
        service = Connection(server, user=settings.bind_dn, password=settings.bind_password,
                             auto_bind=auto_bind, receive_timeout=settings.timeout,
                             raise_exceptions=True)
        stage = "photo_search"
        found = service.search(
            settings.base_dn,
            "(&(objectClass=user)(objectCategory=person)"
            f"(sAMAccountName={escape_filter_chars(username)}))",
            search_scope=SUBTREE,
            attributes=["thumbnailPhoto", "jpegPhoto"],
            size_limit=2,
            time_limit=settings.timeout,
        )
        if not found or len(service.entries) != 1:
            raise DirectoryRejected("Directory account was not found.")
        return _photo_from_entry(service.entries[0])
    except DirectoryRejected:
        raise
    except (LDAPException, OSError) as error:
        ldap_failure(logger, "photo_sync", stage, error)
        raise DirectoryUnavailable("Directory authentication is temporarily unavailable.") from error
    finally:
        if service is not None:
            service.unbind()
