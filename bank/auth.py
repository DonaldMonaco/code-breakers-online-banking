"""F1: customer sign-in with password + one-time code and lockout; sign-out."""
import secrets
import time

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from .config import LOCK_MINUTES, MAX_FAILED, OTP_LIFETIME
from .db import execute, query

bp = Blueprint("auth", __name__)


@bp.route("/", methods=["GET", "POST"])
def login():
    if session.get("role") == "customer":
        return redirect(url_for("customer.accounts"))
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
            csrf = session["csrf"]
            session.clear()
            session["csrf"] = csrf
            session["pending_customer"] = c["customer_id"]
            session["pending_name"] = c["first_name"]
            session["otp"] = code
            session["otp_expires"] = time.time() + OTP_LIFETIME
            session["otp_phone"] = "•••-" + c["phone"][-4:]
            print(f"[demo SMS] one-time code for {username}: {code}", flush=True)
            return redirect(url_for("auth.verify"))
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


@bp.route("/verify", methods=["GET", "POST"])
def verify():
    if "pending_customer" not in session:
        return redirect(url_for("auth.login"))
    if time.time() > session.get("otp_expires", 0):
        session.clear()
        flash("Your code expired. Please sign in again.", "error")
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("code", "").strip(), session["otp"]):
            cid, name = session["pending_customer"], session["pending_name"]
            csrf = session["csrf"]
            session.clear()
            session.update(role="customer", customer_id=cid, name=name,
                           last_seen=time.time(), csrf=csrf)
            return redirect(url_for("customer.accounts"))
        flash("That code is not correct.", "error")
    return render_template("verify.html", demo_code=session["otp"], phone=session["otp_phone"])


@bp.route("/logout", methods=["POST"])
def logout():
    was_staff = session.get("role") == "staff"
    session.clear()
    flash("You have signed out.", "info")
    return redirect(url_for("staff.staff_login" if was_staff else "auth.login"))

