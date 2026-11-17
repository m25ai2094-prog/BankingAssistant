"""Run end-to-end and component checks with the standard library."""

from datetime import date
from decimal import Decimal
import unittest

from banking.money import add_months, deposit_maturity, monthly_emi, paise
from banking.nlu import PortableNLU, RasaNLU
from tools.corpus_io import splits
from .scenarios import CASES, MODEL, run_case


class BankingProjectTests(unittest.TestCase):
    def test_loopback_scenarios(self):
        for case in CASES:
            with self.subTest(case=case[0]):
                report = run_case(*case)
                self.assertEqual(report["status"], "PASS", report["observed"])

    def test_money_components(self):
        for value in ("0", "-0.01", "1e3", "10.123", "NaN", "Infinity", "0.001"):
            with self.subTest(raw=value):
                with self.assertRaises(ValueError):
                    paise(value)
        self.assertEqual(paise("₹12.30"), 1230)
        self.assertEqual(monthly_emi(120000, Decimal("0"), 12), 10000)
        self.assertEqual(monthly_emi(20000000, Decimal(".12"), 24), 941469)
        self.assertEqual(deposit_maturity(1_000_000, Decimal(".065"), 12), 1_066_602)
        self.assertEqual(add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_data_split_and_model(self):
        train, test = splits()
        model = PortableNLU(MODEL)
        self.assertEqual((len(train), len(test), len(model.classes)), (320, 160, 20))
        self.assertEqual(model.parse("🪐").intent, "out_of_scope")
        self.assertGreaterEqual(sum(model.parse(text).intent == label for text, label in test), 100)

    def test_rasa_rejects_nonlocal_url(self):
        for endpoint in ("https://api.example.com/model/parse", "http://127.0.0.1:5005/admin"):
            with self.assertRaises(ValueError):
                RasaNLU(endpoint)


if __name__ == "__main__":
    unittest.main()
