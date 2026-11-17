"""Deterministic multi-turn banking actions, independent of the intent model."""

from decimal import Decimal
from hashlib import sha256
from threading import Lock
from time import monotonic, perf_counter
import re

from .auth import Authentication, Draft, Session, SESSION_TTL
from .catalog import COMPLAINTS, CONTACTS, FD_RATES, LOAN_RATES, RAILS, SERVICES, STEP_UP, TRANSFER_MAX
from .money import add_months, deposit_maturity, inr, monthly_emi, paise
from .nlu import redacted
from .store import BusinessError


MENU = tuple(SERVICES.values())
CONFIRM = ("Confirm", "Cancel")
CANCEL = {"cancel", "cancel request", "stop", "no", "no thanks", "discard", "cancel this request"}
YES = {"yes", "confirm", "yes please", "proceed", "confirm transfer", "confirm booking"}
PRIVATE_STEPS = {
    "identity": "[Demo identity entered]", "otp": "[Verification code entered]",
    "payee_check": "[Beneficiary suffix entered]", "description": "[Demo description entered]",
}
IMMEDIATE = {
    "account_balance_enquiry": "balance",
    "loan_emi_query": "loan",
    "fixed_deposit_enquiry": "deposits",
    "credit_card_statement_request": "statement",
    "credit_card_limit_enquiry": "limit",
    "credit_card_payment_due_enquiry": "due",
}


class ClientError(ValueError):
    """The client should refresh the session or submit a valid turn."""


def reply(message, event, options=(), title=None, rows=(), records=()):
    return {"message": message, "event": event, "options": list(options),
            "title": title, "rows": list(rows), "records": list(records)}


def welcome():
    return reply("Choose a banking service or type a request. The accounts, balances and actions in this demo are fictional.",
                 "session_started", MENU)


class Assistant:
    def __init__(self, store, model, clock=monotonic):
        self.store = store
        self.model = model
        self.clock = clock
        self.auth = Authentication(clock)
        self.sessions = {}
        self.pool_lock = Lock()

    def session(self, key):
        with self.pool_lock:
            session = self.sessions.get(key)
            if session and not session.closed and self.clock() - session.last_activity < SESSION_TTL:
                return session
            return None

    def start(self):
        with self.pool_lock:
            now = self.clock()
            self.sessions = {key: session for key, session in self.sessions.items()
                             if not session.closed and now - session.last_activity < SESSION_TTL}
            if len(self.sessions) >= 256:
                raise ClientError("The local demo session limit was reached. Retry after a session expires.")
            session = Session(last_activity=now)
            self.sessions[session.key] = session
            return session

    def reset(self, session):
        if session:
            with session.lock:
                session.closed = True
                session.draft = None
                self.auth.clear_identity(session)
        return self.start()

    def send(self, session, text, request_id, shortcut=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 400:
            raise ClientError("Enter a message between 1 and 400 characters.")
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ClientError("The request ID is invalid. Retry from the app.")
        clean = text.strip()
        fingerprint = sha256((clean + "\0" + str(shortcut)).encode()).digest()
        with session.lock:
            if session.closed or self.clock() - session.last_activity >= SESSION_TTL:
                raise ClientError("This chat expired. Start a new chat.")
            session.last_activity = self.clock()
            prior = session.cache.get(request_id)
            if prior:
                if prior[0] != fingerprint:
                    raise ClientError("That request ID was already used for a different message.")
                if prior[1]["verified"] and not self.auth.authorized(session):
                    raise ClientError("Verification expired. Start a new request.")
                return prior[1]
            started = perf_counter()
            step = session.draft.step if session.draft else "menu"
            echo = PRIVATE_STEPS.get(step, redacted(clean))
            label = session.draft.intent if session.draft else "out_of_scope"
            source, confidence = "workflow", None
            normalized = clean.casefold().rstrip(".!?").strip()
            if normalized in CANCEL:
                session.draft = None
                session.challenge = None
                label = "deny"
                response = reply("Draft cancelled. Choose a service to continue.", "cancelled", MENU)
            elif session.draft:
                response = self.collect(session, clean, normalized)
            elif normalized in YES:
                label = "affirm"
                response = self.begin(session, label)
            else:
                if isinstance(shortcut, str) and SERVICES.get(shortcut) == clean:
                    label, source = shortcut, "shortcut"
                else:
                    parsed = self.model.parse(redacted(clean))
                    label, confidence, source = parsed.intent, parsed.confidence, "model"
                response = self.begin(session, label)
            response.update({"echo": echo, "step": session.draft.step if session.draft else "menu",
                             "verified": self.auth.authorized(session),
                             "trace": {"intent": label, "source": source, "confidence": confidence,
                                       "elapsed_ms": round((perf_counter() - started) * 1000, 3)}})
            session.cache[request_id] = fingerprint, response
            if len(session.cache) > 64:
                del session.cache[next(iter(session.cache))]
            return response

    def begin(self, session, intent):
        if intent in SERVICES:
            session.draft = Draft(intent, "identity")
            if self.auth.authorized(session):
                return self.resume(session)
            self.auth.clear_identity(session)
            return reply("Enter a fictional customer ID or demo mobile number. Use the Demo records panel for sample values.",
                         "ask_identity")
        if intent == "goodbye":
            self.auth.clear_identity(session)
            return reply("This chat is signed out. Choose a service to start again.", "signed_out", MENU)
        if intent == "greet":
            return welcome()
        if intent in {"affirm", "deny"}:
            return reply("Choose a service before confirming or cancelling.", "no_pending_draft", MENU)
        return reply("I can help with the banking services shown below. Choose one or rephrase your request.",
                     "fallback", MENU)

    def collect(self, session, text, value):
        draft = session.draft
        step = draft.step
        if step == "identity":
            if not re.fullmatch(r"(?:DEMO[0-9]{4}|[0-9]{10})", text, flags=re.IGNORECASE):
                return reply("Use a demo customer ID like DEMO1001 or the sample 10-digit mobile.",
                             "invalid_identity")
            customer = self.store.customer(text)
            return self.issue(session, customer["id"] if customer else None)
        if step == "otp":
            if value == "resend code":
                return self.issue(session, session.challenge.customer_id if session.challenge else None)
            event = self.auth.verify(session, text)
            self.store.event(session.tag, event)
            if event == "verified":
                return self.resume(session)
            messages = {"otp_rejected": "Code rejected. Try the current six-digit demo code.",
                        "otp_format": "Enter exactly six digits.",
                        "otp_expired": "Code expired. Request a new code.",
                        "otp_locked": "Too many attempts. Wait five minutes before verifying in this chat."}
            return reply(messages[event], event, MENU if event == "otp_locked" else ("Resend code", "Cancel"))
        if not self.auth.authorized(session):
            self.auth.clear_identity(session)
            session.draft = Draft(draft.intent, "identity")
            return reply("Verification expired. Verify the demo identity again to restart this draft.",
                         "verification_expired")
        if step == "confirm":
            return self.confirm(session, value)
        try:
            return self.fields(session, text, value)
        except (ValueError, BusinessError) as exc:
            return reply(str(exc), "invalid_field", ("Cancel",))

    def issue(self, session, customer):
        event = self.auth.issue(session, customer)
        if event == "otp_issued":
            session.draft.step = "otp"
            self.store.event(session.tag, event)
            return reply("A verification code appears in Demo inbox when the sample identity matches. Enter the code within five minutes.",
                         event, ("Resend code", "Cancel"))
        messages = {"otp_cooldown": "Wait 15 seconds before requesting another code.",
                    "otp_rate_limited": "The request limit was reached. Try again after five minutes.",
                    "otp_locked": "Verification is temporarily locked in this chat."}
        return reply(messages[event], event, ("Resend code", "Cancel") if session.draft.step == "otp" else ("Cancel",))

    def resume(self, session):
        draft, cid = session.draft, session.customer_id
        intent = draft.intent
        if intent in IMMEDIATE:
            session.draft = None
            return self.read_result(cid, IMMEDIATE[intent])
        start = {
            "transaction_history_request": ("range", "Choose a history period.", ("7 days", "30 days", "90 days")),
            "fund_transfer_initiation": ("payee", "Choose a registered demo beneficiary.",
                                        tuple(p["alias"] for p in self.store.payees(cid))),
            "loan_eligibility_enquiry": ("loan_type", "Choose the demo loan product.", tuple(LOAN_RATES)),
            "fixed_deposit_booking": ("fd_amount", "Enter the deposit principal in rupees, starting at ₹1,000.", ()),
            "credit_card_limit_enhancement": ("limit_amount", "Enter the requested total card limit in rupees.", ()),
            "fraud_alert_report": ("transaction_ref", "Enter an owned transaction reference or choose a recent one.",
                                  tuple(t["reference"] for t in self.store.history(cid, 90)[:4])),
            "grievance_registration": ("category", "Choose a grievance category.", COMPLAINTS),
            "case_status_request": ("case_ref", "Enter a case reference from a saved receipt.", ()),
        }
        if intent == "block_card_request":
            card = self.store.card(cid)
            if card["status"] == "Blocked":
                session.draft = None
                return reply("This demo card is already blocked.", "card_already_blocked", MENU)
            draft.fields.update(kind="card_block", last4=card["last4"])
            return self.review(draft, "Review demo card block", [["Card", "•••• " + card["last4"]]])
        step, message, options = start[intent]
        draft.step = step
        return reply(message, "ask_" + step, options)

    def read_result(self, cid, kind):
        if kind == "balance":
            account = self.store.account(cid)
            return reply("Here are the balances for the verified demo account.", "balance_complete", MENU, "Savings balance",
                         [["Account", "•••• " + account["id"][-4:]], ["Ledger balance", inr(account["balance"])],
                          ["Available balance", inr(account["balance"] - account["held"])]])
        if kind == "loan":
            loan = self.store.loan(cid)
            return reply("Here are the recorded repayment details.", "loan_complete", MENU, loan["reference"],
                         [["Product", loan["product"]], ["Outstanding principal", inr(loan["outstanding"])],
                          ["Monthly EMI", inr(loan["emi"])], ["Next due date", loan["due"]]])
        if kind == "deposits":
            records = [[d["reference"], inr(d["principal"]), inr(d["maturity"]), d["maturity_date"]]
                       for d in self.store.deposits(cid)]
            return reply("Here are the fixed deposits for your verified demo profile.", "deposits_complete", MENU,
                         "Fixed deposits", records=records)
        card = self.store.card(cid)
        rows = [["Card", "•••• " + card["last4"]], ["Status", card["status"]]]
        records = []
        if kind == "limit":
            rows += [["Credit limit", inr(card["credit_limit"])],
                     ["Available credit", inr(card["credit_limit"] - card["outstanding"])],
                     ["Reward points", str(card["rewards"])]]
        else:
            rows += [["Total due", inr(card["outstanding"])], ["Minimum due", inr(card["minimum_due"])],
                     ["Payment due date", card["due"]]]
            if kind == "statement":
                records = [[c["day"], c["merchant"], inr(c["amount"])] for c in self.store.statement(cid)]
        return reply("Here are the details for your verified demo card.", kind + "_complete", MENU, "Credit card", rows, records)

    @staticmethod
    def advance(draft, step, message, options=()):
        draft.step = step
        return reply(message, "ask_" + step, options)

    @staticmethod
    def choose(text, options):
        match = next((option for option in options if option.casefold() == text.casefold()), None)
        if match is None:
            raise ValueError("Choose one of the options shown for this step.")
        return match

    @staticmethod
    def review(draft, title, rows):
        draft.step = "confirm"
        options = ("Confirm", "Change amount", "Cancel") if draft.fields["kind"] in {"transfer", "deposit"} else CONFIRM
        draft.review = {"title": title, "rows": rows, "options": list(options)}
        return reply("Review the details and confirm to record this action in the sandbox.", "review", options, title, rows)

    def fields(self, session, text, value):
        draft, cid = session.draft, session.customer_id
        fields, step = draft.fields, draft.step
        if step == "range":
            fields["days"] = int(self.choose(text, ("7 days", "30 days", "90 days")).split()[0])
            return self.advance(draft, "direction", "Filter by transaction direction.", ("All", "Debit", "Credit"))
        if step == "direction":
            fields["direction"] = self.choose(text, ("All", "Debit", "Credit"))
            return self.advance(draft, "min_amount", "Enter a minimum absolute amount in rupees or choose Any amount.", ("Any amount",))
        if step == "min_amount":
            minimum = 0 if value == "any amount" else paise(text)
            records = [[t["reference"], t["day"], t["kind"], inr(t["amount"]), t["note"]]
                       for t in self.store.history(cid, fields["days"], fields["direction"], minimum)]
            session.draft = None
            return reply(f"Found {len(records)} matching entries. The result is limited to the latest 12.",
                         "history_complete", MENU, "Transaction history", records=records)
        if step == "payee":
            payees = self.store.payees(cid)
            alias = self.choose(text, [p["alias"] for p in payees])
            fields.update(next(p for p in payees if p["alias"] == alias))
            return self.advance(draft, "transfer_amount",
                                f"Enter the transfer amount in rupees for {alias}, account ending {fields['target'][-4:]}.")
        if step == "transfer_amount":
            amount = paise(text)
            account = self.store.account(cid)
            if amount > TRANSFER_MAX:
                raise ValueError("The maximum transfer in this sandbox is ₹5,00,000.")
            if amount > account["balance"] - account["held"]:
                raise ValueError("Insufficient available demo balance. Enter a smaller amount.")
            fields["amount"] = amount
            fields.pop("payee_check", None)
            return self.advance(draft, "rail", "Choose a simulated payment rail.", RAILS)
        if step == "rail":
            fields["rail"] = self.choose(text, RAILS)
            return self.advance(draft, "purpose", "Choose a payment purpose.", ("Personal", "Household", "Education", "Other"))
        if step == "purpose":
            fields["purpose"] = self.choose(text, ("Personal", "Household", "Education", "Other"))
            if fields["amount"] >= STEP_UP:
                return self.advance(draft, "payee_check",
                                    f"For this demo amount, re-enter the beneficiary suffix {fields['target'][-4:]}.")
            return self.transfer_review(draft)
        if step == "payee_check":
            if text != fields["target"][-4:]:
                raise ValueError("The beneficiary suffix did not match. Re-enter its four digits.")
            fields["payee_check"] = text
            return self.transfer_review(draft)
        if step == "loan_type":
            fields["product"] = self.choose(text, tuple(LOAN_RATES))
            return self.advance(draft, "loan_amount", "Enter a proposed loan principal in rupees.")
        if step == "loan_amount":
            fields["amount"] = paise(text)
            return self.advance(draft, "loan_tenure", "Enter a tenure from 6 to 360 months.")
        if step == "loan_tenure":
            if not text.isdigit() or len(text) > 3 or not 6 <= int(text) <= 360:
                raise ValueError("Enter a whole number of months from 6 to 360.")
            profile = self.store.customer(cid)
            rate = LOAN_RATES[fields["product"]]
            emi = monthly_emi(fields["amount"], rate, int(text))
            ratio = Decimal(profile["obligations"] + emi) / profile["income"]
            eligible = profile["score"] >= 650 and ratio <= Decimal("0.45")
            session.draft = None
            return reply("This estimate applies the synthetic credit score and repayment limits.",
                         "eligibility_complete", MENU, "Demo loan estimate",
                         [["Product", fields["product"]], ["Sample annual rate", f"{rate:.2%}"],
                          ["Estimated EMI", inr(emi)], ["Debt to income", f"{ratio:.2%}"],
                          ["Demo outcome", "Meets sample criteria" if eligible else "Outside sample criteria"]])
        if step == "fd_amount":
            amount = paise(text)
            if not 100_000 <= amount <= TRANSFER_MAX:
                raise ValueError("Enter a principal from ₹1,000 to ₹5,00,000.")
            fields["amount"] = amount
            return self.advance(draft, "fd_tenure", "Choose a fixed-deposit tenure.", tuple(f"{m} months" for m in FD_RATES))
        if step == "fd_tenure":
            months = int(self.choose(text, tuple(f"{m} months" for m in FD_RATES)).split()[0])
            rate = FD_RATES[months]
            fields.update(months=months, kind="deposit")
            return self.review(draft, "Review fixed deposit", [["Principal", inr(fields["amount"])],
                               ["Annual rate", f"{rate:.2%}"],
                               ["Quoted maturity", inr(deposit_maturity(fields["amount"], rate, months))],
                               ["Maturity date", add_months(self.store.today(), months).isoformat()]])
        if step == "limit_amount":
            amount = paise(text)
            if not self.store.card(cid)["credit_limit"] < amount <= 100_000_000:
                raise ValueError("Choose a demo limit above the current limit and up to ₹10,00,000.")
            fields.update(kind="case", subject=inr(amount))
            return self.review_case(draft, "Limit review")
        if step == "transaction_ref":
            reference = text.upper()
            if not self.store.transaction(cid, reference):
                raise ValueError("No matching transaction was found for this verified profile.")
            fields.update(subject=reference, case_kind="Fraud alert")
            return self.advance(draft, "description", "Describe the suspicious demo transaction in 12 to 240 characters.")
        if step == "category":
            fields.update(subject=self.choose(text, COMPLAINTS), case_kind="Grievance")
            return self.advance(draft, "description", "Describe the demo complaint in 12 to 240 characters.")
        if step == "description":
            if not 12 <= len(text) <= 240:
                raise ValueError("Enter a fictional description of 12 to 240 characters.")
            fields["description"] = text
            if fields["case_kind"] == "Grievance":
                return self.advance(draft, "contact", "Choose a demo contact preference.", CONTACTS)
            return self.review_case(draft, fields["case_kind"])
        if step == "contact":
            fields["contact"] = self.choose(text, CONTACTS)
            return self.review_case(draft, fields["case_kind"])
        if step == "case_ref":
            record = self.store.case(cid, text.upper())
            if not record:
                return reply("No matching case was found for this verified profile.", "case_not_found", ("Cancel",))
            session.draft = None
            return reply("Here is the case recorded for your verified profile.", "case_complete", MENU, record["reference"],
                         [["Type", record["kind"]], ["Status", record["status"]], ["Opened", record["opened"]]])
        raise RuntimeError("Unknown banking workflow step.")

    def transfer_review(self, draft):
        fields = draft.fields
        fields["kind"] = "transfer"
        return self.review(draft, "Review simulated transfer",
                           [["Beneficiary", fields["alias"] + " · •••• " + fields["target"][-4:]],
                            ["Amount", inr(fields["amount"])], ["Demo rail", fields["rail"]], ["Purpose", fields["purpose"]]])

    def review_case(self, draft, kind):
        draft.fields.update(kind="case", case_kind=kind)
        return self.review(draft, "Review " + kind.lower(),
                           [["Type", kind], ["Subject", draft.fields["subject"]],
                            ["Contact", draft.fields.get("contact", "In-app")]])

    def confirm(self, session, value):
        draft = session.draft
        fields = draft.fields
        kind = fields["kind"]
        if value == "change amount" and kind in {"transfer", "deposit"}:
            step = "transfer_amount" if kind == "transfer" else "fd_amount"
            return self.advance(draft, step, "Enter the revised amount in rupees.")
        if value not in YES:
            return reply("Choose Confirm or Cancel to resolve the draft.", "awaiting_confirmation", CONFIRM)
        payload = {**fields, "kind": fields["case_kind"]} if kind == "case" else fields
        try:
            result = self.store.commit(session.customer_id, draft.token, kind, payload, session.tag)
        except BusinessError as exc:
            session.draft = None
            return reply(str(exc), "commit_rejected", MENU)
        session.draft = None
        return reply("Action recorded in the local banking sandbox.", kind + "_complete", MENU,
                     result["reference"], [["Status", result["status"]], *result["rows"]])
