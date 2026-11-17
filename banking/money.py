"""Money and product calculations. Monetary state is stored in integer paise."""

from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import re


def paise(text: str) -> int:
    value = text.strip().removeprefix("₹").strip()
    if not re.fullmatch(r"[0-9]{1,7}(?:\.[0-9]{1,2})?", value):
        raise ValueError("Enter a positive amount in rupees with up to two decimal places.")
    result = int(Decimal(value) * 100)
    if result <= 0:
        raise ValueError("Enter an amount greater than zero.")
    return result


def inr(amount: int) -> str:
    sign = "−" if amount < 0 else ""
    whole, fraction = divmod(abs(amount), 100)
    digits = str(whole)
    rest, last = digits[:-3], digits[-3:]
    parts = []
    while rest:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    return f"{sign}₹{','.join(parts + [last])}.{fraction:02d}"


def rounded(amount: Decimal) -> int:
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def monthly_emi(principal: int, annual_rate: Decimal, months: int) -> int:
    if months <= 0 or principal <= 0 or annual_rate < 0:
        raise ValueError("Use a positive principal and tenure, and a nonnegative rate.")
    rate = annual_rate / 12
    if rate == 0:
        return rounded(Decimal(principal) / months)
    growth = (1 + rate) ** months
    return rounded(Decimal(principal) * rate * growth / (growth - 1))


def deposit_maturity(principal: int, annual_rate: Decimal, months: int) -> int:
    if months <= 0 or months % 3:
        raise ValueError("The sample FD tenure must contain whole quarters.")
    return rounded(Decimal(principal) * (1 + annual_rate / 4) ** (months // 3))


def add_months(today: date, months: int) -> date:
    year, offset = divmod(today.year * 12 + today.month - 1 + months, 12)
    month = offset + 1
    return date(year, month, min(today.day, monthrange(year, month)[1]))
