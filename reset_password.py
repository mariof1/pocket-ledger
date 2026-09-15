"""Reset a Pocket Ledger account from the server console.

The new password is read interactively so it is not exposed in command history.
"""

import argparse
import getpass
import sys

from app import reset_account_password


def main():
    parser = argparse.ArgumentParser(description="Reset a local Pocket Ledger password")
    parser.add_argument("--email", required=True, help="Account email address")
    args = parser.parse_args()
    password = getpass.getpass("New password (12–128 characters): ")
    confirm = getpass.getpass("Confirm new password: ")
    if password != confirm:
        print("Passwords did not match.", file=sys.stderr)
        return 1
    try:
        found = reset_account_password(args.email, password)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    if not found:
        print("Account not found.", file=sys.stderr)
        return 1
    print("Password reset. Existing sessions were signed out.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
