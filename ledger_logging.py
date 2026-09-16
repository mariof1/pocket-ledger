"""Small, stdout-based operational logs for Docker and Portainer."""

import logging
import os
import re
import sys
import time


def configure_logging():
    logger = logging.getLogger("pocket_ledger")
    level_name = os.environ.get("LEDGER_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    invalid_level = not isinstance(level, int) or level_name not in ("DEBUG", "INFO", "WARNING", "ERROR")
    if invalid_level:
        level = logging.INFO
        level_name = "INFO"
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)sZ %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
        )
        formatter.converter = time.gmtime
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    if invalid_level:
        logger.warning("invalid_log_level default=INFO")
    return logger


def ldap_failure(logger, operation, stage, error):
    """Report the failure stage and safe diagnostics without dumping LDAP data."""
    detail = str(error).lower()
    if "certificate verify failed" in detail or "cert_verify_failed" in detail:
        reason = "certificate_verification"
    elif "invalidcredentials" in detail or "invalid credentials" in detail:
        reason = "invalid_credentials"
    elif "timed out" in detail or "timeout" in detail:
        reason = "timeout"
    elif "name or service not known" in detail or "name resolution" in detail:
        reason = "dns"
    elif "connection refused" in detail:
        reason = "connection_refused"
    else:
        reason = "ldap_error"
    ldap_result = getattr(error, "result", None)
    ad_code = re.search(r"\bdata ([0-9a-f]{3,4})\b", detail)
    logger.warning("directory_failure operation=%s stage=%s reason=%s exception=%s result=%s ad_code=%s",
                   operation, stage, reason, type(error).__name__,
                   ldap_result if isinstance(ldap_result, int) else "unknown",
                   ad_code.group(1) if ad_code else "none")
