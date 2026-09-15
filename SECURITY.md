# Security policy

Pocket Ledger handles passwords and financial records. For a suspected vulnerability, use GitHub's **Report a vulnerability** option on this repository's Security tab so details can be reviewed privately. Do not include credentials, databases, exported account files or signing keys in public issues or pull requests.

The current `0.1.x` release line receives security fixes. Update to the newest release image and keep SQLite data and `secret.key` in a private persistent volume. Remote access requires an HTTPS reverse proxy; the supplied Compose files bind the host port to loopback.
