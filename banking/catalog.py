"""Public service labels and synthetic product parameters."""

from decimal import Decimal

SERVICES = {
    "account_balance_enquiry": "Check balance",
    "transaction_history_request": "Transaction history",
    "fund_transfer_initiation": "Transfer money",
    "loan_eligibility_enquiry": "Loan eligibility",
    "loan_emi_query": "Existing loan EMI",
    "fixed_deposit_booking": "Book a fixed deposit",
    "fixed_deposit_enquiry": "View fixed deposits",
    "credit_card_statement_request": "Card statement",
    "credit_card_limit_enquiry": "Card limit and rewards",
    "credit_card_payment_due_enquiry": "Card payment due",
    "credit_card_limit_enhancement": "Request a higher card limit",
    "fraud_alert_report": "Report a suspicious transaction",
    "block_card_request": "Block demo card",
    "grievance_registration": "Register a grievance",
    "case_status_request": "Track a case",
}

CONTROL = ("greet", "affirm", "deny", "goodbye", "out_of_scope")
INTENTS = set(SERVICES) | set(CONTROL)
RAILS = ("UPI", "IMPS", "NEFT", "RTGS")
TRANSFER_MAX = 50_000_000
STEP_UP = 2_500_000
LOAN_RATES = {
    "Home": Decimal("0.085"),
    "Personal": Decimal("0.12"),
    "Auto": Decimal("0.095"),
    "Education": Decimal("0.105"),
}
FD_RATES = {6: Decimal("0.058"), 12: Decimal("0.065"),
            24: Decimal("0.068"), 36: Decimal("0.07")}
COMPLAINTS = ("Charges", "Digital banking", "Branch service", "Other")
CONTACTS = ("In-app", "Demo email")

DEMO_IDENTITIES = (
    {"id": "DEMO1001", "mobile": "0000001001", "name": "Aarav Mehta",
     "account": "SB-1001", "balance": 12_500_000, "income": 8_500_000,
     "obligations": 1_450_000, "score": 735, "card": "4242"},
    {"id": "DEMO1002", "mobile": "0000001002", "name": "Meera Rao",
     "account": "SB-2002", "balance": 6_800_000, "income": 5_000_000,
     "obligations": 1_800_000, "score": 620, "card": "5186"},
    {"id": "DEMO1003", "mobile": "0000001003", "name": "Kiran Shah",
     "account": "SB-3003", "balance": 3_000_000, "income": 6_000_000,
     "obligations": 600_000, "score": 702, "card": "6098"},
)
