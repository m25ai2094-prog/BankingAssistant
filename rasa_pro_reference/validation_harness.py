from decimal import Decimal, InvalidOperation

def validate(raw):
    balance = Decimal("1000.00")
    try:
        amount = Decimal(str(raw))
        if (not amount.is_finite() or amount <= 0
                or amount != amount.quantize(Decimal("0.01"))):
            return "invalid"
        if amount > balance:
            return "insufficient"
        return "valid"
    except (InvalidOperation, ValueError, TypeError):
        return "invalid"

cases = [
    (500, "valid"), (1000, "valid"),
    ("1000.01", "insufficient"), (1500, "insufficient"),
    (0, "invalid"), (-50, "invalid"),
    ("0.01", "valid"), ("0.001", "invalid"),
    ("12.345", "invalid"), ("12.30", "valid"),
    (None, "invalid"), ("", "invalid"),
    ("abc", "invalid"), ("NaN", "invalid"),
    ("Infinity", "invalid"), (True, "invalid"),
]
for raw, expected in cases:
    actual = validate(raw)
    assert actual == expected, (raw, expected, actual)
    print(repr(raw), actual, "PASS")
print("16/16 component cases passed")
