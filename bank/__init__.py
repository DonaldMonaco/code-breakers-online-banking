"""Code Breakers Online Banking: Flask application factory."""
import mysql.connector
from flask import Flask, render_template, session

from . import auth, customer, staff
from .config import SECRET_KEY
from .db import close_db
from .formatting import mask, money
from .security import security_checks


def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

    app.before_request(security_checks)
    app.teardown_appcontext(close_db)
    app.add_template_filter(money, "money")
    app.add_template_filter(mask, "mask")

    @app.context_processor
    def inject_globals():
        return {"csrf_token": session.get("csrf"), "who": session.get("name"),
                "role": session.get("role")}

    app.register_blueprint(auth.bp)
    app.register_blueprint(customer.bp)
    app.register_blueprint(staff.bp)

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("message.html", title="Not found",
                               text="That page or record does not exist, or it is not yours."), 404

    @app.errorhandler(mysql.connector.Error)
    def db_down(e):
        app.logger.error("Database error: %s", e)
        return render_template("message.html", title="Database unavailable",
                               text="The app could not reach the online_banking database. "
                                    "Check that MySQL is running and DB_PASSWORD is set correctly."), 503

    return app
