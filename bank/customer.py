"""F2-F7: accounts, transaction history, and transfers (form -> review -> confirm -> receipt)."""
import uuid
import warnings
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import mysql.connector
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from .db import db, query
from .formatting import mask, money
from .security import customer_required, own_account

bp = Blueprint("customer", __name__)


def _stored_results(cur):
    """Result sets returned by a stored procedure (works on old and new mysql-connector versions)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        results = cur.stored_results
        return results() if callable(results) else results


@bp.route("/accounts")
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
@bp.route("/accounts/<account_no>/history")
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
@bp.route("/transfer", methods=["GET", "POST"])
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
            return redirect(url_for("customer.review"))
    return render_template("transfer.html", accounts=accts, form=form)


@bp.route("/transfer/review")
@customer_required
def review():
    p = session.get("pending_transfer")
    if not p:
        return redirect(url_for("customer.transfer"))
    src, dst = own_account(p["source"]), own_account(p["dest"])
    amount = Decimal(p["amount"])
    return render_template("review.html", p=p, src=src, dst=dst, amount=amount,
                           src_after=src["available_balance"] - amount,
                           dst_after=dst["available_balance"] + amount)


@bp.route("/transfer/confirm", methods=["POST"])
@customer_required
def confirm():
    p = session.get("pending_transfer")
    if not p or request.form.get("request_id") != p["request_id"]:
        flash("This transfer was already handled or has expired. Please start again.", "error")
        return redirect(url_for("customer.transfer"))
    cur = db().cursor(dictionary=True)
    try:
        cur.callproc("sp_transfer", (session["customer_id"], p["request_id"],
                                     p["source"], p["dest"], Decimal(p["amount"])))
        result = None
        for rs in _stored_results(cur):
            result = rs.fetchone() or result
    except mysql.connector.Error as e:
        cur.close()
        # SQLSTATE 45000 messages come from the business rules in sp_transfer
        msg = e.msg if e.errno == 1644 else "The transfer could not be completed. No money was moved."
        flash(msg, "error")
        return redirect(url_for("customer.transfer"))
    cur.close()
    ref = result["reference_no"] if isinstance(result, dict) else result[1]
    return redirect(url_for("customer.receipt", reference_no=ref))


@bp.route("/receipt/<reference_no>")
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

