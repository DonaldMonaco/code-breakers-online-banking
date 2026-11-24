"""Database access: one MySQL connection per request, plus small query helpers."""
import mysql.connector
from flask import g

from .config import DB_CONFIG


def db():
    """Return this request's connection, opening it on first use."""
    if "db" not in g:
        g.db = mysql.connector.connect(**DB_CONFIG)
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def query(sql, params=(), one=False):
    """Run a SELECT and return rows as dicts (or one dict / None when one=True)."""
    cur = db().cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, params=()):
    """Run an INSERT/UPDATE/DELETE."""
    cur = db().cursor()
    cur.execute(sql, params)
    cur.close()
