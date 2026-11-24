"""Display helpers used by the templates."""
from decimal import Decimal


def money(value):
    """1234.5 -> $1,234.50"""
    return "${:,.2f}".format(Decimal(value or 0))


def mask(account_no):
    """4000001024 -> ••••1024 (only the last four digits are ever shown)."""
    return "••••" + str(account_no)[-4:]
