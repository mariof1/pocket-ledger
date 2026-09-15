# Pocket Ledger improvement plan

The work is staged so each release is usable and can be checked against an isolated database before updating the live server.

## Build 1 — monthly clarity and interface polish (implemented)

- Show recorded income, spending, and cash flow as transaction figures; label cash flow as a flow rather than an account balance.
- Show the monthly planning average for bills and commuting separately from actual scheduled bill occurrences.
- Summarise scheduled, linked-to-transaction, and unrecorded bill payments for the selected month, including due-now and upcoming amounts. Flag non-monthly bills without a first payment date. Never silently treat a similar manual transaction as a linked bill payment.
- Improve small-text contrast, type size, keyboard focus, and form errors. Preserve entered values when validation fails.
- Verify account/profile isolation, weekly and yearly schedules, edited payment amounts, desktop layout, and live-data preservation.

## Build 2 — reviewed statement import

- Accept common CSV statement formats through a review screen with column mapping, dates, amount signs, and category suggestions.
- Detect exact and probable duplicates before saving. Let the user skip, edit, and confirm rows in one atomic batch.
- Keep import history per profile and make a failed batch leave no partial transactions.

## Build 3 — accounts, balances, and transfers

- Add current, savings, and card accounts inside each profile, with opening balances and transaction ownership.
- Represent transfers explicitly so moving money between owned accounts changes balances without inflating income or spending.
- Migrate existing profile transactions safely and keep exported data portable across versions.

## Build 4 — maintainable app structure

- Split server routes and domain calculations, with versioned SQLite migrations and a rollback/backup procedure.
- Split the browser script into API/state, pages, forms, and calculators; organise CSS into tokens, components, and page styles.
- Add focused checks for the new import and account flows, responsive layouts, and accessible form behaviour.

Build 1 passed isolated server and mortgage-guide tests, a populated desktop review, a 390-pixel responsive check without horizontal overflow, live database integrity and record-count comparisons against a local backup, and an invalid-form review without saving test records. The later builds are planned work and will need their own data-model and interface review before release.
