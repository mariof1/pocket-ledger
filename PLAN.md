# Pocket Ledger improvement plan

The work is staged so each release is usable and can be checked against an isolated database before updating the live server.

## Build 1 — monthly clarity and interface polish (implemented)

- Show recorded income, spending, and cash flow as transaction figures; label cash flow as a flow rather than an account balance.
- Show the monthly planning average for bills and commuting separately from actual scheduled bill occurrences.
- Summarise scheduled, linked-to-transaction, and unrecorded bill payments for the selected month, including due-now and upcoming amounts. Flag non-monthly bills without a first payment date. Never silently treat a similar manual transaction as a linked bill payment.
- Improve small-text contrast, type size, keyboard focus, and form errors. Preserve entered values when validation fails.
- Verify account/profile isolation, weekly and yearly schedules, edited payment amounts, desktop layout, and live-data preservation.

## Build 2 — reviewed statement import (implemented)

- Accept comma, semicolon and tab-separated bank CSVs through a review screen with column mapping, date order, signed amount or debit/credit columns, decimal marks, and category suggestions from matching saved descriptions.
- Detect exact and probable duplicates before saving. Let the user skip or edit rows and explicitly acknowledge a legitimate repeat; recheck on the server inside one atomic batch.
- Keep import history and source-row links per profile, prevent importing the same source row again, and include history in account export/import.

## Build 3 — accounts, balances, and transfers

- Add current, savings, and card accounts inside each profile, with opening balances and transaction ownership.
- Represent transfers explicitly so moving money between owned accounts changes balances without inflating income or spending.
- Migrate existing profile transactions safely and keep exported data portable across versions.

## Build 4 — maintainable app structure

- Split server routes and domain calculations, with versioned SQLite migrations and a rollback/backup procedure.
- Split the browser script into API/state, pages, forms, and calculators; organise CSS into tokens, components, and page styles.
- Add focused checks for the new import and account flows, responsive layouts, and accessible form behaviour.

Build 1 passed isolated server and mortgage-guide tests, a populated desktop review, a 390-pixel responsive check without horizontal overflow, live database integrity and record-count comparisons against a local backup, and an invalid-form review without saving test records. Build 2 passed isolated CSV parsing, duplicate/rollback/profile and export/import checks, the full regression suite, a live-data backup and integrity check, and a desktop and phone-width review using a test CSV without saving it to the live account. Builds 3 and 4 are planned work and will need their own data-model and interface review before release.
