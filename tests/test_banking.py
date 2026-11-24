"""
Automated tests for the Code Breakers online banking app.

They run against a real online_banking database, so load it first:
    mysql -h 127.0.0.1 -u root -p < database/online_banking_db.sql
Then, from the project folder:
    DB_PASSWORD='your-mysql-password' python3 -m pytest -v
If the database can't be reached, the database tests are skipped.
"""
import os
import re
from decimal import Decimal

import mysql.connector
import pytest

os.environ.setdefault("DB_PASSWORD", "")
from bank import create_app  # noqa: E402
from bank.config import DB_CONFIG  # noqa: E402
from bank.formatting import mask, money  # noqa: E402


# --------------------------------------------------------------------------
# Unit tests (no database needed)
# --------------------------------------------------------------------------
def test_money_format():
    assert money(Decimal("1234.5")) == "$1,234.50"
    assert money(0) == "$0.00"


def test_mask_shows_only_last_four():
    assert mask("4000001024") == "••••1024"


# --------------------------------------------------------------------------
# Database tests
# --------------------------------------------------------------------------
def _db_available():
    try:
        mysql.connector.connect(**DB_CONFIG).close()
        return True
    except mysql.connector.Error:
        return False


needs_db = pytest.mark.skipif(not _db_available(), reason="online_banking database not reachable")


def sql(statement, params=(), one=False):
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)
    cur.execute(statement, params)
    rows = cur.fetchall() if cur.with_rows else None
    conn.close()
    return (rows[0] if rows else None) if one else rows


def balances():
    return {r["account_no"]: r["available_balance"] for r in sql("SELECT account_no, available_balance FROM account")}


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def csrf(client):
    client.get("/")
    with client.session_transaction() as s:
        return s["csrf"]


def sign_in_customer(client, username="mlopez", password="Maria2026!"):
    token = csrf(client)
    r = client.post("/", data={"csrf": token, "username": username, "password": password})
    assert r.status_code == 302 and r.headers["Location"].endswith("/verify")
    with client.session_transaction() as s:
        code = s["otp"]
    r = client.post("/verify", data={"csrf": token, "code": code})
    assert r.headers["Location"].endswith("/accounts")
    return token


def review_transfer(client, token, source, dest, amount):
    return client.post("/transfer", data={"csrf": token, "source": source, "dest": dest, "amount": amount},
                       follow_redirects=True)


@needs_db
def test_wrong_password_is_rejected(client):
    token = csrf(client)
    r = client.post("/", data={"csrf": token, "username": "mlopez", "password": "nope"})
    assert b"Username or password is incorrect" in r.data
    sql("UPDATE customer SET failed_attempts = 0 WHERE username = 'mlopez'")


@needs_db
def test_wrong_one_time_code_is_rejected(client):
    token = csrf(client)
    client.post("/", data={"csrf": token, "username": "mlopez", "password": "Maria2026!"})
    r = client.post("/verify", data={"csrf": token, "code": "not-it"})
    assert b"That code is not correct" in r.data


@needs_db
def test_five_wrong_passwords_lock_the_account(client):
    token = csrf(client)
    try:
        for _ in range(5):
            r = client.post("/", data={"csrf": token, "username": "jchen", "password": "wrong"})
        assert b"locked for 15 minutes" in r.data
        r = client.post("/", data={"csrf": token, "username": "jchen", "password": "James2026!"})
        assert b"Too many wrong attempts" in r.data
    finally:
        sql("UPDATE customer SET failed_attempts = 0, locked_until = NULL WHERE username = 'jchen'")


@needs_db
def test_accounts_page_shows_only_own_accounts(client):
    sign_in_customer(client)
    page = client.get("/accounts").data.decode()
    assert "••••1024" in page and "••••2048" in page
    assert "••••3072" not in page            # James Chen's account
    assert client.get("/accounts/4000003072/history").status_code == 404


@needs_db
def test_transfer_rules(client):
    token = sign_in_customer(client)
    before = balances()
    assert b"Choose two different accounts" in review_transfer(client, token, "4000001024", "4000001024", "10").data
    assert b"Enter an amount greater than $0" in review_transfer(client, token, "4000001024", "4000002048", "0").data
    assert b"at most two decimal places" in review_transfer(client, token, "4000001024", "4000002048", "1.005").data
    assert b"Insufficient funds" in review_transfer(client, token, "4000001024", "4000002048", "999999").data
    assert b"Choose a From account" in review_transfer(client, token, "4000001024", "4000003072", "10").data
    assert balances() == before


@needs_db
def test_transfer_moves_money_once(client):
    token = sign_in_customer(client)
    before = balances()
    review_transfer(client, token, "4000001024", "4000002048", "12.34")
    with client.session_transaction() as s:
        request_id = s["pending_transfer"]["request_id"]

    r = client.post("/transfer/confirm", data={"csrf": token, "request_id": request_id})
    ref = re.search(r"/receipt/(TRF\d+)", r.headers["Location"]).group(1)
    after = balances()
    assert after["4000001024"] == before["4000001024"] - Decimal("12.34")
    assert after["4000002048"] == before["4000002048"] + Decimal("12.34")
    assert sum(after.values()) == sum(before.values())            # money moved, not created

    postings = sql("""SELECT t.txn_type, t.amount FROM account_transaction t JOIN transfer x USING (transfer_id)
                      WHERE x.reference_no = %s ORDER BY txn_type""", (ref,))
    assert [(p["txn_type"], p["amount"]) for p in postings] == [("CREDIT", Decimal("12.34")), ("DEBIT", Decimal("12.34"))]

    # Confirming the same request again (double click) must not move money twice
    client.post("/transfer/confirm", data={"csrf": token, "request_id": request_id})
    assert balances() == after
    assert sql("SELECT COUNT(*) AS n FROM transfer WHERE request_id = %s", (request_id,), one=True)["n"] == 1


@needs_db
def test_staff_lookup_is_logged_and_staff_cannot_transfer(client):
    token = csrf(client)
    r = client.post("/staff", data={"csrf": token, "username": "arivera", "password": "Staff2026!"})
    assert r.headers["Location"].endswith("/staff/search")
    count = sql("SELECT COUNT(*) AS n FROM transfer_review", one=True)["n"]
    r = client.post("/staff/search", data={"csrf": token, "reference_no": "TRF000001", "reason": "automated test"},
                    follow_redirects=True)
    assert b"Transfer TRF000001" in r.data and b"automated test" in r.data
    assert sql("SELECT COUNT(*) AS n FROM transfer_review", one=True)["n"] == count + 1
    assert client.get("/transfer").headers["Location"].endswith("/staff/search")


@needs_db
def test_forms_without_csrf_token_are_refused(client):
    assert client.post("/", data={"username": "mlopez", "password": "Maria2026!"}).status_code == 400
