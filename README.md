# Code Breakers Online Banking (CSC 430 Midterm)

A Python/Flask web app that runs on the `online_banking` MySQL database.

## What it does
| Requirement | Page |
|---|---|
| F1 Sign in with password + one-time code, lock after 5 wrong passwords for 15 min | `/` then `/verify` |
| F2 Accounts with masked numbers and balances | `/accounts` |
| F3 Transaction history by date range | `/accounts/<number>/history` |
| F4–F7 Transfer between own accounts → review → confirm → receipt (one transfer per request, even on double click) | `/transfer` |
| N4 Sign out after 5 minutes without activity | all pages |
| F10 / N5 Staff look up transfers by reference number; every lookup is logged with a reason | `/staff` |

Transfers call the `sp_transfer` stored procedure, so balances and history are updated in one database transaction.

## Demo sign-ins
| Who | Username | Password |
|---|---|---|
| Customer (2 accounts) | `mlopez` | `Maria2026!` |
| Customer (1 account) | `jchen` | `James2026!` |
| Staff | `arivera` | `Staff2026!` |

No real text message is sent: the one-time code is shown on the screen in a yellow "Demo mode" box (and printed in Terminal).

## Run it (Mac)
1. Load (or reload) the database. This resets it to the sample data with the demo passwords:
   ```
   /usr/local/mysql/bin/mysql --no-defaults -h 127.0.0.1 -P 3306 -u root -p < online_banking_db.sql
   ```
2. In the `banking_app` folder, set up Python once:
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
4. Open **http://127.0.0.1:5050** in your browser. Press Ctrl+C in Terminal to stop.

## Database settings
By default the app connects to `127.0.0.1:3306` as `root` with password `Banking2026`.
If yours is different, set it before starting, for example:
```
DB_PASSWORD=YourPassword python3 app.py
```
Other settings: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_NAME`.

## Files
- `app.py` – all routes and database queries
- `templates/` – the HTML pages
- `static/style.css` – styling
- `online_banking_db.sql` – the database script (same as the report appendix)
