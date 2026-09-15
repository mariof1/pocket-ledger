# Pocket Ledger

A private web app for tracking income, spending, monthly category budgets, regular bills and savings goals. Each account can create up to ten separate profiles, each with its own records and currency (GBP, EUR or USD). Categories are saved per profile and can be picked again in bills, transactions and budgets. The overview shows monthly cash flow, savings rate, spending categories and a six-month income/spending chart. The Transactions page searches and pages through history in groups of 50. The calculators estimate mortgage repayments, mortgage affordability, savings growth and the cost of a repeating spending habit.

Savings goals with a target date compare the remaining balance and current monthly contribution with the time left. When the pace is too slow, the goal card shows an estimated monthly amount needed to reach the target, assuming one contribution in each available calendar month. A passed target date is flagged; a completed goal does not show a warning.

Regular bills can be daily, weekly, every two weeks, every four weeks, monthly, every three months, or yearly. Enter the amount paid each time; Bills, Overview, and Budgets show its average monthly planning cost. A weekly amount uses 52 ÷ 12, a yearly amount uses 1 ÷ 12, and each monthly equivalent rounds to the nearest cent. Actual calendar months can contain a different number of payments. Bills are planning entries and do not create spending transactions automatically. Existing bills upgrade as monthly without changing their amounts or due days.

To record paid bills, choose the month on **Regular bills** and click **Import into transactions**. The review lists actual scheduled payment occurrences, their full payment amounts and due dates. Click **Select all ready**, uncheck anything you have not paid, then **Import selected**. Future payments and payments already imported are unavailable. A similar manually entered expense is flagged and omitted from Select all ready; check it yourself only if it really is a separate payment. Monthly bills use their saved day of month (clipped to the last day in short months). For weekly, quarterly, yearly and other non-monthly bills, save a **First payment date** on the bill so the app can find actual occurrences. Without that date, the review offers a shortcut to edit the bill. Imported payments appear in actual spending, cash flow, budgets and Transactions; monthly planning averages remain separate. If the actual payment date or amount differs, edit the transaction after import or enter it manually. Commuting plans are estimates and are not offered for import.

Transactions record payments that have happened, so the form accepts dates through today. Older future-dated transactions, if any, remain visible and editable in Transactions but are excluded from actual spending, budgets, recent activity and the overview chart until their date arrives. Use Regular Bills and commuting plans for future planning amounts.

Use **Duplicate** beside a transaction to open a prefilled new-transaction form. It copies the type, amount, category and note, sets the date to today, and saves a separate record only after you review and submit the form. A duplicated bill payment is a normal transaction and is not linked to the bill-import history.

To move records to another user, open **Profiles & settings → Export all data** and keep the downloaded JSON file private. It contains every profile with its transactions, budgets, goals, bills, commuting plans, saved categories, and imported-bill payment links. It does not contain the account email, password, signing key or sign-in sessions. Create the new user account, then use **Import data** in that new account's settings and select the export file. Import is available only while that account has its one initial empty profile; it replaces that empty profile with the exported profiles and rejects accounts that already contain records. The operation is atomic, so an invalid file does not leave partial records. Files up to 50 MB are accepted. Keep a separate backup of the server's `instance` directory if you need to move credentials or recover the full server.

Regular Bills also has commuting plans. Choose Car for daily round-trip miles, **UK imperial mpg**, and fuel price per litre in your profile currency; the estimate covers fuel. Choose Public transport for a daily return fare. Choose the weekdays you actually commute, enter annual leave or other days off as dates or inclusive date ranges (`YYYY-MM-DD..YYYY-MM-DD`), and optionally exclude official UK bank holidays for your region. [GOV.UK's bank-holiday JSON](https://www.gov.uk/bank-holidays.json) supplies the dates when available; the app warns if the data cannot be checked. Bank holidays are included by default because [employers do not have to give paid leave on those dates](https://www.gov.uk/bank-holidays). The month picker shows that month's expected commuting days and cost. Commuting adds to the Bills, Overview, and Budgets planning total for the selected month, while actual spending remains based on recorded transactions. Add parking, tolls, or other non-fuel costs as separate regular bills if needed.

In a commuting plan, choose **Annual leave allowance — monthly estimate** and enter a whole number such as 25 if you do not know the dates. The number should be days that would otherwise be commuting days. The app spreads it across the calendar year in proportion to the selected commuting weekdays in each month, after any selected bank holidays; those holidays are not counted within the annual allowance. The resulting month cost is an estimate, because the exact timing of leave is unknown. Choose **Exact dates — precise month** when you know the dates. Existing commuting plans retain their saved exact dates after upgrading. Displayed estimated day counts round to two decimals; costs are calculated before that display rounding.

The UK mortgage affordability view compares the loan against selected published income-multiple limits from Nationwide, HSBC and Santander, checked on 15 September 2026. Select a property type for Santander's over-90% LTV screen, because the published house and flat limits differ. After 45 days without a criteria review, the calculator stops claiming a loan fits a sampled published cap and asks the user to open the current lender links. It also compares the estimated monthly repayment with the take-home pay and costs you enter and shows a scenario with an interest rate two percentage points higher. The scenario is a personal planning check; it does not reproduce a lender's private affordability model. Published income multiples are ceilings, and a lender's Agreement or Decision in Principle is needed for a personalised borrowing estimate. Calculator inputs stay in the browser and are not saved to SQLite.

## Run locally

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000), create an account with a password of at least 12 characters, and start adding records. The app starts on the local computer only. To choose another port, set `LEDGER_PORT` before running it.

SQLite data, server-side sessions and the signing key are kept in `instance/`, which is excluded from Git. Back up that directory to retain accounts and financial records. Existing accounts must sign in once after upgrading from a version that used cookie-only sessions. Set `LEDGER_INSTANCE` to use a different data directory. `LEDGER_SECRET_KEY` can override the generated signing key.

Change your password in Profiles & settings; this signs out other sessions. If you forget it, the server owner can reset it from a console on the server:

```powershell
.venv\Scripts\python.exe reset_password.py --email your@email.com
```

The command prompts for the new password without putting it in command history and signs out all existing sessions for that account.

For access from another device, keep Pocket Ledger bound to loopback and configure an HTTPS reverse proxy on the same server that forwards to `127.0.0.1:5000`. Set `LEDGER_HTTPS=1` when the browser connects to the proxy over HTTPS so cookies use the Secure flag. The app refuses a non-loopback `LEDGER_HOST` value. Review the linked official lender criteria before updating `static/mortgage-guide.js` caps and its checked date; the embedded caps are a dated planning snapshot.

## Verify

```powershell
.venv\Scripts\python.exe -m unittest -v test_app.py
node --check static/app.js
node --test test_mortgage_guide.js
```
