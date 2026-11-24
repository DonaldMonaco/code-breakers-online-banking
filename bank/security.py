"""Security shared by every page: CSRF check, inactivity timeout, access decorators."""
import secrets
import time
from functools import wraps

from flask import abort, flash, redirect, request, session, url_for

from .config import SESSION_TIMEOUT
from .db import query


def security_checks():
    """Runs before every request (registered in create_app)."""
    session.setdefault("csrf", secrets.token_hex(16))
    if request.method == "POST" and request.form.get("csrf") != session["csrf"]:
        abort(400, "Form expired. Go back, reload the page and try again.")

    if session.get("role"):
        last = session.get("last_seen", 0)
        if time.time() - last > SESSION_TIMEOUT:
            session.clear()
            flash("You were signed out after 5 minutes without activity.", "info")
            return redirect(url_for("auth.login"))
        session["last_seen"] = time.time()


def customer_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") == "staff":
            flash("Staff accounts can look up transfers but cannot use customer banking.", "error")
            return redirect(url_for("staff.staff_search"))
        if session.get("role") != "customer":
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped


def staff_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if session.get("role") != "staff":
            return redirect(url_for("staff.staff_login"))
        return view(*args, **kwargs)
    return wrapped


def own_account(account_no):
    """Return the account only if it belongs to the signed-in customer."""
    return query("SELECT * FROM account WHERE account_no = %s AND customer_id = %s",
                 (account_no, session["customer_id"]), one=True)
