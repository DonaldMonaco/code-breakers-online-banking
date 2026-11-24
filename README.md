# Code Breakers Online Banking

CSC 430 final project, Team Code Breakers: Donald Monaco, Justin Fuquen, Zhi Zhang, Ting Xu Zheng, Stephen Mai.

A web application for online self-service banking. Existing customers sign in with a password and a one-time code, view their checking and savings balances, filter their transaction history by date, and transfer money between their own accounts. Bank staff look up transfers by reference number, and every lookup is recorded.

The app is written in Python with Flask and runs on a MySQL database (`online_banking`). All money rules are enforced in the database itself, and every transfer runs as one database transaction.

**Release:** `v1.0-uat`, the baseline for User Acceptance Testing.

## Features and requirements

| Requirement | What the user can do | Where |
|---|---|---|
| F1 | Sign in with a password and a 6-digit one-time code. 5 wrong passwords lock sign-in for 15 minutes | `bank/auth.py` |
| F2 | See their accounts with masked numbers and available balances | `bank/customer.py` |
| F3 | See an account's transaction history for a date range, newest first | `bank/customer.py` |
| F4–F6 | Transfer between their own accounts: form, review with balances after, confirm, receipt | `bank/customer.py`, `sp_transfer` |
| F7 | A double click or retry never moves money twice | `sp_transfer` (unique `request_id`) |
| N4 | Signed out after 5 minutes without activity | `bank/security.py` |
| F10, N5 | Staff look up a transfer by reference number; each lookup is logged with a reason; staff cannot move money | `bank/staff.py` |

## Project structure

```
code-breakers-online-banking/
├── app.py                     Starts the web app
├── bank/                      The application, one module per area
│   ├── __init__.py            Builds the app and connects the modules
│   ├── config.py              Settings (database connection, time limits)
│   ├── db.py                  Database connection and query helpers
│   ├── security.py            Form protection, inactivity timeout, access checks
│   ├── formatting.py          Money and account-number display
│   ├── auth.py                Customer sign-in, one-time code, sign-out
│   ├── customer.py            Accounts, history, transfers, receipt
│   ├── staff.py               Staff sign-in, transfer lookup, access log
│   ├── templates/             HTML pages (one per screen)
│   └── static/style.css       Styling
├── database/
│   └── online_banking_db.sql  Creates the database, tables, stored procedure and sample data
├── tests/
│   └── test_banking.py        Automated tests
└── docs/                      Lab 4 report, E-R diagram, presentation
```

## Module descriptions

| Module | Purpose | Main functions |
|---|---|---|
| `app.py` | Entry point. Asks for the MySQL password if it isn't set, then starts the server on port 5050 | — |
| `bank/__init__.py` | Application factory. Registers the three page modules, the display filters, and the error pages ("Not found", "Database unavailable") | `create_app()` |
| `bank/config.py` | All settings in one place, read from environment variables so no password is stored in the code | `DB_CONFIG`, `SESSION_TIMEOUT`, `MAX_FAILED`, `LOCK_MINUTES` |
| `bank/db.py` | Opens one MySQL connection per web request and closes it afterwards. Every query uses parameters (`%s`), never string building, which prevents SQL injection | `query()`, `execute()` |
| `bank/security.py` | Runs before every request: checks the hidden form token (CSRF protection) and signs out idle users. Provides the access checks that keep customers and staff to their own pages | `security_checks()`, `customer_required`, `staff_required`, `own_account()` |
| `bank/formatting.py` | Shows money as `$1,234.50` and account numbers as `••••1024` | `money()`, `mask()` |
| `bank/auth.py` | Customer sign-in. Checks the password hash, counts failed attempts, locks the account after 5, creates the one-time code (shown on screen in demo mode instead of sent by text) | `login()`, `verify()`, `logout()` |
| `bank/customer.py` | Customer pages. Validates transfer amounts and accounts, keeps the pending transfer and its request ID in the session, and calls the `sp_transfer` stored procedure on confirm | `accounts()`, `history()`, `transfer()`, `review()`, `confirm()`, `receipt()` |
| `bank/staff.py` | Staff pages. Requires a reason for every lookup and saves it in `transfer_review` before showing the transfer | `staff_login()`, `staff_search()`, `staff_transfer()` |
| `database/online_banking_db.sql` | Six tables with keys and CHECK constraints, indexes, the `sp_transfer` stored procedure, and sample data | `sp_transfer` |

### How a transfer works

1. `transfer()` checks the form: two different accounts that belong to the customer, an amount over $0 with at most 2 decimals, enough money.
2. `review()` shows the balances after the transfer. A new request ID is created for this review.
3. `confirm()` calls `sp_transfer`. In one database transaction it locks both accounts, checks ownership and funds again, saves the transfer and a debit and a credit, and updates both balances. Any failure rolls everything back.
4. If the same request ID arrives again, `sp_transfer` returns the original transfer instead of moving money twice.
5. `receipt()` shows the reference number (e.g. `TRF000002`) and the new balances.

## Database

Six tables: `customer`, `account`, `transfer`, `account_transaction`, `staff`, `transfer_review`. The E-R diagram and data dictionary are in `docs/`.

## Setup

You need Python 3.10 or newer and MySQL 8.0.16 or newer, running on `127.0.0.1:3306`.

1. Load the database. This also resets it to the sample data:
   ```
   mysql -h 127.0.0.1 -u root -p < database/online_banking_db.sql
   ```
   On a Mac with the MySQL installer, use `/usr/local/mysql/bin/mysql` instead of `mysql`.
2. Install the Python packages (once):
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Start the app:
   ```
   source .venv/bin/activate
   python3 app.py
   ```
   Type your MySQL password when asked, or set it first with `export DB_PASSWORD='your-password'`.
4. Open **http://127.0.0.1:5050**. Press Ctrl+C to stop.

Other settings (optional environment variables): `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_NAME`, `SECRET_KEY`.

## Test accounts

| Role | Username | Password | Notes |
|---|---|---|---|
| Customer | `mlopez` | `Maria2026!` | Checking ••••1024 and Savings ••••2048 |
| Customer | `jchen` | `James2026!` | Checking ••••3072 |
| Staff | `arivera` | `Staff2026!` | Sign in at `/staff` |

These are demo accounts in the sample data only. Passwords are stored as PBKDF2 hashes, never as plain text. In demo mode the one-time code appears on screen in a yellow box.

## Running the tests

With the database loaded:
```
export DB_PASSWORD='your-password'
python3 -m pytest -v
```
The 10 tests cover sign-in, wrong codes, lockout, account privacy, every transfer rule, a full transfer (balances, postings, total unchanged), double-submit protection, the staff audit log, and form protection. Tests that need the database are skipped if it can't be reached.
