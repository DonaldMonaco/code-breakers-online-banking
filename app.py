"""
Code Breakers Online Banking - web application for the online_banking database
CSC 430 Lab 4

Run:   python3 app.py      then open http://127.0.0.1:5050
"""
import os
import secrets
import time
import uuid
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps

import mysql.connector
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash

# ---------------------------------------------------------------------------
# Settings (change with environment variables if your setup is different)
# ---------------------------------------------------------------------------
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "3306")),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASSWORD", "Banking2026"),
    "database": os.environ.get("DB_NAME", "online_banking"),
    "autocommit": True,
}
SESSION_TIMEOUT = 5 * 60      # N4: sign out after 5 minutes without activity
OTP_LIFETIME = 5 * 60         # one-time code is valid for 5 minutes
MAX_FAILED = 5                # F1: lock after 5 wrong passwords ...
LOCK_MINUTES = 15             # ... for 15 minutes

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def db():
    """One connection per request, closed automatically afterwards."""
    if "db" not in g:
        g.db = mysql.connector.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, params=(), one=False):
    cur = db().cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, params=()):
    cur = db().cursor()
    cur.execute(sql, params)
    cur.close()


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------
@app.template_filter("money")
def money(value):
    return "${:,.2f}".format(Decimal(value or 0))


@app.template_filter("mask")
def mask(account_no):
    return "••••" + str(account_no)[-4:]


@app.context_processor
def inject_globals():
    return {"csrf_token": session.get("csrf"), "who": session.get("name"),
            "role": session.get("role")}


# ---------------------------------------------------------------------------
# Security: CSRF token, inactivity timeout, login-required decorators
# ---------------------------------------------------------------------------
@app.before_request
def security_checks():
    session.setdefault("csrf", secrets.token_hex(16))
    if request.method == "POST" and request.form.get("csrf") != session["csrf"]:
        abort(400, "Form expired. Go back, reload the page and try again.")

    if session.get("role"):
        last = session.get("last_seen", 0)
        if time.time() - last > SESSION_TIMEOUT:
            session.clear()
            flash("You were signed out after 5 minutes without activity.", "info")
            return redirect(url_for("login"))
        session["last_seen"] = time.time()


def customer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") == "staff":
            flash("Staff accounts can look up transfers but cannot use customer banking.", "error")
            return redirect(url_for("staff_search"))
        if session.get("role") != "customer":
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def staff_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "staff":
            return redirect(url_for("staff_login"))
        return view(*args, **kwargs)
    return wrapped


def own_account(account_no):
    """Return the account only if it belongs to the signed-in customer."""
    return query("SELECT * FROM account WHERE account_no = %s AND customer_id = %s",
                 (account_no, session["customer_id"]), one=True)


# ---------------------------------------------------------------------------
# F1: customer sign-in (password + one-time code, lockout)
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if session.get("role") == "customer":
        return redirect(url_for("accounts"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        c = query("""SELECT customer_id, first_name, phone, password_hash, failed_attempts,
                            locked_until, locked_until > NOW() AS is_locked,
                            CEIL(TIMESTAMPDIFF(SECOND, NOW(), locked_until) / 60) AS mins_left
                       FROM customer WHERE username = %s""", (username,), one=True)
        if c and c["is_locked"]:
            flash(f"Too many wrong attempts. Try again in {int(c['mins_left'])} minute(s).", "error")
        elif c and check_password_hash(c["password_hash"], password):
            execute("UPDATE customer SET failed_attempts = 0, locked_until = NULL WHERE customer_id = %s",
                    (c["customer_id"],))
            code = f"{secrets.randbelow(10**6):06d}"
            session.clear()
            session["pending_customer"] = c["customer_id"]
            session["pending_name"] = c["first_name"]
            session["otp"] = code
            session["otp_expires"] = time.time() + OTP_LIFETIME
            session["otp_phone"] = "•••-" + c["phone"][-4:]
            print(f"[demo SMS] one-time code for {username}: {code}", flush=True)
            return redirect(url_for("verify"))
        else:
            if c:
                attempts = c["failed_attempts"] + 1
                if attempts >= MAX_FAILED:
                    execute("""UPDATE customer SET failed_attempts = 0,
                                   locked_until = NOW() + INTERVAL %s MINUTE
                                WHERE customer_id = %s""", (LOCK_MINUTES, c["customer_id"]))
                    flash(f"Too many wrong attempts. Sign-in is locked for {LOCK_MINUTES} minutes.", "error")
                    return render_template("login.html")
                execute("UPDATE customer SET failed_attempts = %s WHERE customer_id = %s",
                        (attempts, c["customer_id"]))
            # Same message whether the username exists or not
            flash("Username or password is incorrect.", "error")
    return render_template("login.html")


@app.route("/verify", methods=["GET", "POST"])
def verify():
    if "pending_customer" not in session:
        return redirect(url_for("login"))
    if time.time() > session.get("otp_expires", 0):
        session.clear()
        flash("Your code expired. Please sign in again.", "error")
        return redirect(url_for("login"))
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("code", "").strip(), session["otp"]):
            cid, name = session["pending_customer"], session["pending_name"]
            csrf = session["csrf"]
            session.clear()
            session.update(role="customer", customer_id=cid, name=name,
                           last_seen=time.time(), csrf=csrf)
            return redirect(url_for("accounts"))
        flash("That code is not correct.", "error")
    return render_template("verify.html", demo_code=session["otp"], phone=session["otp_phone"])


@app.route("/logout", methods=["POST"])
def logout():
    was_staff = session.get("role") == "staff"
    session.clear()
    flash("You have signed out.", "info")
    return redirect(url_for("staff_login" if was_staff else "login"))


# ---------------------------------------------------------------------------
# F2: accounts and balances
# ---------------------------------------------------------------------------
@app.route("/accounts")
@customer_required
def accounts():
    rows = query("""SELECT account_no, account_type, available_balance, status
                      FROM account WHERE customer_id = %s ORDER BY account_type""",
                 (session["customer_id"],))
    total = sum(r["available_balance"] for r in rows)
    return render_template("accounts.html", accounts=rows, total=total)


# ---------------------------------------------------------------------------
# F3: transaction history with date range
# ---------------------------------------------------------------------------
@app.route("/accounts/<account_no>/history")
@customer_required
def history(account_no):
    acct = own_account(account_no)
    if not acct:
        abort(404)
    today = date.today()
    try:
        start = date.fromisoformat(request.args.get("start") or str(today - timedelta(days=30)))
        end = date.fromisoformat(request.args.get("end") or str(today))
    except ValueError:
        flash("Enter dates as YYYY-MM-DD.", "error")
        start, end = today - timedelta(days=30), today
    if start > end:
        flash("The start date must be on or before the end date.", "error")
        start, end = end, start
    rows = query("""SELECT posted_at, description, txn_type, amount, balance_after
                      FROM account_transaction
                     WHERE account_no = %s AND posted_at >= %s AND posted_at < %s
                     ORDER BY posted_at DESC, txn_id DESC""",
                 (account_no, start, end + timedelta(days=1)))
    return render_template("history.html", acct=acct, rows=rows, start=start, end=end)


# ---------------------------------------------------------------------------
# F4-F7: transfer between own accounts -> review -> confirm -> receipt
# ---------------------------------------------------------------------------
@app.route("/transfer", methods=["GET", "POST"])
@customer_required
def transfer():
    accts = query("""SELECT account_no, account_type, available_balance FROM account
                      WHERE customer_id = %s AND status = 'ACTIVE' ORDER BY account_type""",
                  (session["customer_id"],))
    form = {"source": request.form.get("source", ""), "dest": request.form.get("dest", ""),
            "amount": request.form.get("amount", "")}

    if request.method == "POST":
        error = None
        src, dst = own_account(form["source"]), own_account(form["dest"])
        try:
            amount = Decimal(form["amount"].replace(",", "").replace("$", "").strip())
        except InvalidOperation:
            amount = None
        if not src or not dst:
            error = "Choose a From account and a To account."
        elif src["account_no"] == dst["account_no"]:
            error = "Choose two different accounts."
        elif amount is None or amount <= 0:
            error = "Enter an amount greater than $0."
        elif amount != amount.quantize(Decimal("0.01")):
            error = "Amounts can have at most two decimal places."
        elif amount > src["available_balance"]:
            error = f"Insufficient funds. {mask(src['account_no'])} has {money(src['available_balance'])} available."
        if error:
            flash(error, "error")
        else:
            # A new request_id for each review screen; confirming twice reuses it (F7).
            session["pending_transfer"] = {"request_id": str(uuid.uuid4()),
                                           "source": src["account_no"], "dest": dst["account_no"],
                                           "amount": str(amount)}
            return redirect(url_for("review"))
    return render_template("transfer.html", accounts=accts, form=form)


@app.route("/transfer/review")
@customer_required
def review():
    p = session.get("pending_transfer")
    if not p:
        return redirect(url_for("transfer"))
    src, dst = own_account(p["source"]), own_account(p["dest"])
    amount = Decimal(p["amount"])
    return render_template("review.html", p=p, src=src, dst=dst, amount=amount,
                           src_after=src["available_balance"] - amount,
                           dst_after=dst["available_balance"] + amount)


@app.route("/transfer/confirm", methods=["POST"])
@customer_required
def confirm():
    p = session.get("pending_transfer")
    if not p or request.form.get("request_id") != p["request_id"]:
        flash("This transfer was already handled or has expired. Please start again.", "error")
        return redirect(url_for("transfer"))
    cur = db().cursor(dictionary=True)
    try:
        cur.callproc("sp_transfer", (session["customer_id"], p["request_id"],
                                     p["source"], p["dest"], Decimal(p["amount"])))
        result = None
        for rs in cur.stored_results():
            result = rs.fetchone() or result
    except mysql.connector.Error as e:
        cur.close()
        # SQLSTATE 45000 messages come from the business rules in sp_transfer
        msg = e.msg if e.errno == 1644 else "The transfer could not be completed. No money was moved."
        flash(msg, "error")
        return redirect(url_for("transfer"))
    cur.close()
    ref = result["reference_no"] if isinstance(result, dict) else result[1]
    return redirect(url_for("receipt", reference_no=ref))


@app.route("/receipt/<reference_no>")
@customer_required
def receipt(reference_no):
    t = query("""SELECT t.*, s.account_type AS src_type, d.account_type AS dst_type,
                        s.available_balance AS src_balance, d.available_balance AS dst_balance
                   FROM transfer t
                   JOIN account s ON s.account_no = t.source_acct_no
                   JOIN account d ON d.account_no = t.dest_acct_no
                  WHERE t.reference_no = %s AND s.customer_id = %s""",
              (reference_no, session["customer_id"]), one=True)
    if not t:
        abort(404)
    return render_template("receipt.html", t=t)


# ---------------------------------------------------------------------------
# F10 / N5: staff lookup with audit trail (staff cannot make transfers)
# ---------------------------------------------------------------------------
@app.route("/staff", methods=["GET", "POST"])
def staff_login():
    if session.get("role") == "staff":
        return redirect(url_for("staff_search"))
    if request.method == "POST":
        s = query("SELECT * FROM staff WHERE username = %s",
                  (request.form.get("username", "").strip(),), one=True)
        if s and check_password_hash(s["password_hash"], request.form.get("password", "")):
            csrf = session["csrf"]
            session.clear()
            session.update(role="staff", staff_id=s["staff_id"], name=s["first_name"],
                           staff_role=s["staff_role"], last_seen=time.time(), csrf=csrf)
            return redirect(url_for("staff_search"))
        flash("Username or password is incorrect.", "error")
    return render_template("staff_login.html")


@app.route("/staff/search", methods=["GET", "POST"])
@staff_required
def staff_search():
    if request.method == "POST":
        ref = request.form.get("reference_no", "").strip().upper()
        reason = request.form.get("reason", "").strip()
        if not reason:
            flash("Enter a reason. Every lookup is recorded.", "error")
            return render_template("staff_search.html", ref=ref, reason=reason)
        t = query("SELECT transfer_id FROM transfer WHERE reference_no = %s", (ref,), one=True)
        if not t:
            flash(f"No transfer found with reference {ref}.", "error")
            return render_template("staff_search.html", ref=ref, reason=reason)
        execute("INSERT INTO transfer_review (staff_id, transfer_id, reason) VALUES (%s, %s, %s)",
                (session["staff_id"], t["transfer_id"], reason[:200]))
        return redirect(url_for("staff_transfer", reference_no=ref))
    return render_template("staff_search.html", ref="", reason="")


@app.route("/staff/transfer/<reference_no>")
@staff_required
def staff_transfer(reference_no):
    t = query("""SELECT t.reference_no, t.amount, t.status, t.created_at, t.completed_at,
                        t.source_acct_no, t.dest_acct_no, t.transfer_id,
                        CONCAT(c.first_name, ' ', c.last_name) AS customer
                   FROM transfer t
                   JOIN account a  ON a.account_no = t.source_acct_no
                   JOIN customer c ON c.customer_id = a.customer_id
                  WHERE t.reference_no = %s""", (reference_no,), one=True)
    if not t:
        abort(404)
    reviews = query("""SELECT r.reviewed_at, r.reason, CONCAT(s.first_name, ' ', s.last_name) AS staff_name
                         FROM transfer_review r JOIN staff s ON s.staff_id = r.staff_id
                        WHERE r.transfer_id = %s ORDER BY r.reviewed_at DESC""", (t["transfer_id"],))
    return render_template("staff_transfer.html", t=t, reviews=reviews)


@app.errorhandler(404)
def not_found(_e):
    return render_template("message.html", title="Not found",
                           text="That page or record does not exist, or it is not yours."), 404


@app.errorhandler(mysql.connector.Error)
def db_down(e):
    app.logger.error("Database error: %s", e)
    return render_template("message.html", title="Database unavailable",
                           text="The app could not reach the online_banking database. "
                                "Check that MySQL is running and the settings at the top of app.py are right."), 503


if __name__ == "__main__":
    print("Online Banking is running at  http://127.0.0.1:5050   (press Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=5050, debug=False)
