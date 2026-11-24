"""F10 / N5: staff sign-in and transfer lookup with an audit trail. Staff cannot move money."""
import time

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .db import execute, query
from .security import staff_required

bp = Blueprint("staff", __name__)


@bp.route("/staff", methods=["GET", "POST"])
def staff_login():
    if session.get("role") == "staff":
        return redirect(url_for("staff.staff_search"))
    if request.method == "POST":
        s = query("SELECT * FROM staff WHERE username = %s",
                  (request.form.get("username", "").strip(),), one=True)
        if s and check_password_hash(s["password_hash"], request.form.get("password", "")):
            csrf = session["csrf"]
            session.clear()
            session.update(role="staff", staff_id=s["staff_id"], name=s["first_name"],
                           staff_role=s["staff_role"], last_seen=time.time(), csrf=csrf)
            return redirect(url_for("staff.staff_search"))
        flash("Username or password is incorrect.", "error")
    return render_template("staff_login.html")


@bp.route("/staff/search", methods=["GET", "POST"])
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
        return redirect(url_for("staff.staff_transfer", reference_no=ref))
    return render_template("staff_search.html", ref="", reason="")


@bp.route("/staff/transfer/<reference_no>")
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

