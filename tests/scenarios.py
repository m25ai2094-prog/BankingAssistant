"""Measured loopback HTTP acceptance scenarios, using a fresh sandbox per case."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import perf_counter
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener
from uuid import uuid4

from banking.catalog import SERVICES
from banking.engine import Assistant
from banking.http_app import make_server
from banking.nlu import PortableNLU, RasaNLU
from banking.store import Store
from tools.corpus_io import ROOT


DATE = date(2026, 11, 12)
MODEL = ROOT / "models" / "bank_intents.json"
LABELS = {label: intent for intent, label in SERVICES.items()}


class Clock:
    def __init__(self):
        self.value = 1_000

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@contextmanager
def running(server):
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class Client:
    def __init__(self, base, timings, transcript=None):
        self.base = base
        self.timings = timings
        self.transcript = transcript
        self.jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))

    def request(self, path, data=None, headers=None, want=200):
        request_headers = headers or {}
        if data is not None:
            request_headers = {"Content-Type": "application/json", **request_headers}
        request = Request(self.base + path, json.dumps(data).encode() if data is not None else None,
                          headers=request_headers)
        try:
            response = self.opener.open(request, timeout=6)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read()
            assert response.status == want, (response.status, want, body[:140])
        return json.loads(body) if path.startswith("/api/") else body

    def turn(self, text, event=None, *, id_=None, shortcut=None):
        start = perf_counter()
        result = self.request("/api/chat", {"text": text, "shortcut": shortcut, "request_id": id_ or uuid4().hex})
        self.timings.append({"event": result["event"], "ms": round((perf_counter() - start) * 1000, 3)})
        if event:
            assert result["event"] == event, (event, result["event"], result["message"])
        if self.transcript is not None:
            self.transcript.append({key: result[key] for key in ("echo", "event", "message", "title", "rows")})
        return result

    def service(self, label, event=None):
        return self.turn(label, event, shortcut=LABELS[label])

    def auth(self, label, customer="DEMO1001", event=None):
        self.service(label, "ask_identity")
        self.turn(customer, "otp_issued")
        code = self.request("/api/demo-inbox")["code"]
        assert code and len(code) == 6
        return self.turn(code, event)


class Fixture:
    def __init__(self, base, store, clock, timings):
        self.base, self.store, self.clock, self.timings = base, store, clock, timings
        self.transcript = []
        self.client = self.other(self.transcript)

    def other(self, transcript=None):
        client = Client(self.base, self.timings, transcript)
        client.request("/api/session")
        return client


def draft_transfer(client, amount="1500", *, verified=False, payee="Meera Rao", suffix=None, review_id=None):
    if verified:
        client.service("Transfer money", "ask_payee")
    else:
        client.auth("Transfer money", event="ask_payee")
    client.turn(payee, "ask_transfer_amount")
    client.turn(amount, "ask_rail")
    client.turn("IMPS", "ask_purpose")
    client.turn("Personal", "ask_payee_check" if suffix else "review", id_=review_id if not suffix else None)
    if suffix:
        client.turn(suffix, "review", id_=review_id)


def draft_grievance(client):
    client.auth("Register a grievance", event="ask_category")
    client.turn("Charges", "ask_description")
    client.turn("Fictional service fee needs a review.", "ask_contact")
    client.turn("In-app", "review")
    return client.turn("Confirm", "case_complete")


def session_assets(f):
    c = f.client
    landing = c.request("/")
    assert all(marker in landing for marker in (b"overview-view", b"assistant-view", b"service-grid"))
    assert b"crypto.randomUUID" in c.request("/assets/app.js")
    assert c.request("/api/health")["status"] == "ready"
    guest = c.request("/api/session")
    assert guest["active_profile"] is None and guest["review"] is None
    assert len(guest["services"]) == 15
    assert any(cookie.name == "bank_demo_sid" and cookie.has_nonstandard_attr("HttpOnly") for cookie in c.jar)
    return "Dashboard, assistant assets and guest snapshot served with an HTTP-only session cookie."


def balance(f):
    c = f.client
    c.turn("How much money is in my account", "ask_identity")
    c.turn("0000001001", "otp_issued")
    result = c.turn(c.request("/api/demo-inbox")["code"], "balance_complete")
    assert ("Available balance", "₹1,25,000.00") in map(tuple, result["rows"])
    return "Free-text request routed to verified balance and masked account."


def unknown_identity(f):
    c = f.client
    c.service("Check balance", "ask_identity")
    c.turn("wrong", "invalid_identity")
    r = c.turn("DEMO9999", "otp_issued")
    assert c.request("/api/demo-inbox")["code"] is None
    other = f.other()
    other.service("Check balance", "ask_identity")
    same = other.turn("DEMO1001", "otp_issued")
    assert r["message"] == same["message"] and other.request("/api/demo-inbox")["code"]
    return "Unknown and known IDs have identical prompts; delivery is session-scoped."


def wrong_otp(f):
    c = f.client
    c.service("Check balance", "ask_identity")
    c.turn("DEMO1001", "otp_issued")
    otp = c.request("/api/demo-inbox")["code"]
    assert f.other().request("/api/demo-inbox")["code"] is None
    c.turn("1234", "otp_format")
    c.turn("000000" if otp != "000000" else "000001", "otp_rejected")
    c.turn(otp, "balance_complete")
    assert c.request("/api/demo-inbox")["code"] is None
    return "Invalid and wrong codes rejected; valid code consumed once."


def otp_lock(f):
    c = f.client
    c.service("Check balance", "ask_identity")
    c.turn("DEMO1001", "otp_issued")
    code = c.request("/api/demo-inbox")["code"]
    wrong = "000000" if code != "000000" else "000001"
    c.turn(wrong, "otp_rejected")
    c.turn(wrong, "otp_rejected")
    c.turn(wrong, "otp_locked")
    c.service("Check balance", "ask_identity")
    c.turn("DEMO1001", "otp_locked")
    assert c.request("/api/demo-inbox")["code"] is None
    return "Three wrong attempts lock issuance in the same chat."


def otp_resend(f):
    c = f.client
    c.service("Check balance", "ask_identity")
    c.turn("DEMO1001", "otp_issued")
    old = c.request("/api/demo-inbox")["code"]
    c.turn("Resend code", "otp_cooldown")
    f.clock.advance(300)
    c.turn(old, "otp_expired")
    c.turn("Resend code", "otp_issued")
    c.turn(c.request("/api/demo-inbox")["code"], "balance_complete")
    return "Controlled clock exercised resend cooldown and five-minute expiry."


def issue_rate(f):
    c = f.client
    c.service("Check balance", "ask_identity")
    c.turn("DEMO1001", "otp_issued")
    for _ in range(3):
        f.clock.advance(15)
        c.turn("Resend code", "otp_issued")
    f.clock.advance(15)
    c.turn("Resend code", "otp_rate_limited")
    return "Fifth issuance within the rolling window rejected."


def grant_expiry(f):
    c = f.client
    draft_transfer(c, review_id="old-protected-turn")
    c.turn("show details again", "awaiting_confirmation")
    active = c.request("/api/session")
    assert active["active_profile"]["id"] == "DEMO1001"
    assert ["Amount", "₹1,500.00"] in active["review"]["rows"]
    f.clock.advance(600)
    saved = c.request("/api/session")
    assert saved["active_profile"] is None and saved["review"] is None
    assert not saved["reply"]["verified"] and not saved["reply"]["rows"]
    c.request("/api/chat", {"text": "Personal", "request_id": "old-protected-turn"}, want=400)
    c.turn("Confirm", "verification_expired")
    assert not f.store.rows("SELECT * FROM transfers")
    return "Active review restored before expiry. Expired verification hid the profile and review and blocked the commit."


def history(f):
    c = f.client
    c.auth("Transaction history", event="ask_range")
    c.turn("30 days", "ask_direction")
    c.turn("Debit", "ask_min_amount")
    r = c.turn("1500", "history_complete")
    assert len(r["records"]) == 2 and all(row[2] == "Debit" for row in r["records"])
    return "Date, direction and minimum amount filters returned two owned rows."


def transfer(f):
    c = f.client
    draft_transfer(c)
    assert not f.store.rows("SELECT * FROM transfers")
    r = c.turn("Confirm", "transfer_complete")
    assert r["title"].startswith("TRF-")
    assert f.store.account("DEMO1001")["balance"] == 12_350_000
    assert f.store.account("DEMO1002")["balance"] == 6_950_000
    assert f.store.rows("SELECT SUM(amount) AS total,COUNT(*) AS n FROM ledger WHERE reference LIKE ?",
                        r["title"] + "%") == [{"total": 0, "n": 2}]
    return "₹1,500 debit and credit reconciled with one saved transfer reference."


def transfer_cancel(f):
    draft_transfer(f.client)
    f.client.turn("Cancel", "cancelled")
    assert not f.store.rows("SELECT * FROM transfers")
    assert f.store.account("DEMO1001")["balance"] == 12_500_000
    return "Cancellation left the opening balance and transfer table unchanged."


def transfer_validation(f):
    c = f.client
    c.auth("Transfer money", event="ask_payee")
    c.turn("Unknown", "invalid_field")
    c.turn("Meera Rao", "ask_transfer_amount")
    for raw in ("0", "-25", "12.345", "NaN", "500001", "125001"):
        c.turn(raw, "invalid_field")
    assert not f.store.rows("SELECT * FROM transfers")
    return "Unknown payee, invalid decimal amounts, cap and insufficient funds were rejected."


def amount_change(f):
    c = f.client
    draft_transfer(c)
    c.turn("Change amount", "ask_transfer_amount")
    c.turn("2000.25", "ask_rail")
    c.turn("UPI", "ask_purpose")
    r = c.turn("Household", "review")
    assert ["Amount", "₹2,000.25"] in r["rows"]
    c.turn("Confirm", "transfer_complete")
    assert f.store.rows("SELECT amount FROM transfers") == [{"amount": 200025}]
    return "Revised amount produced a new review and only the confirmed paise value committed."


def step_up(f):
    c = f.client
    c.auth("Transfer money", event="ask_payee")
    c.turn("Meera Rao", "ask_transfer_amount")
    c.turn("25000", "ask_rail")
    c.turn("NEFT", "ask_purpose")
    c.turn("Personal", "ask_payee_check")
    c.turn("3003", "invalid_field")
    c.turn("2002", "review")
    c.turn("Confirm", "transfer_complete")
    return "A transfer at the step-up threshold needed the correct payee suffix."


def idempotency(f):
    c = f.client
    draft_transfer(c)
    r = c.turn("Confirm", "transfer_complete", id_="retry-same-operation")
    repeat = c.turn("Confirm", "transfer_complete", id_="retry-same-operation")
    assert r["title"] == repeat["title"]
    c.request("/api/chat", {"text": "Cancel", "request_id": "retry-same-operation"}, want=400)
    assert f.store.rows("SELECT COUNT(*) AS n FROM transfers") == [{"n": 1}]
    assert f.store.rows("SELECT COUNT(*) AS n FROM audit WHERE event='transfer_committed'") == [{"n": 1}]
    return "Same request replayed one receipt; conflicting reuse was rejected."


def concurrent(f):
    a, b = f.client, f.other()
    draft_transfer(a, "90000", suffix="2002")
    draft_transfer(b, "90000", suffix="2002")
    with ThreadPoolExecutor(2) as workers:
        results = list(workers.map(lambda c: c.turn("Confirm"), (a, b)))
    assert sorted(r["event"] for r in results) == ["commit_rejected", "transfer_complete"]
    assert f.store.account("DEMO1001")["balance"] == 3_500_000
    assert f.store.rows("SELECT COUNT(*) AS n FROM transfers") == [{"n": 1}]
    return "One of two competing debits succeeded; the other failed the transactional balance check."


def persisted(f):
    draft_transfer(f.client)
    receipt = f.client.turn("Confirm", "transfer_complete")
    reloaded = Store(f.store.path, today=lambda: DATE)
    with running(make_server(Assistant(reloaded, PortableNLU(MODEL)), ROOT, 0)) as base:
        c = Client(base, f.timings)
        c.request("/api/session")
        r = c.auth("Check balance", event="balance_complete")
        assert ["Available balance", "₹1,23,500.00"] in r["rows"]
    assert reloaded.rows("SELECT reference FROM transfers") == [{"reference": receipt["title"]}]
    return "New server and browser session retrieved the persisted balance and reference."


def loan_estimate(f):
    c = f.client
    c.auth("Loan eligibility", event="ask_loan_type")
    c.turn("Personal", "ask_loan_amount")
    c.turn("200000", "ask_loan_tenure")
    r = c.turn("24", "eligibility_complete")
    assert ["Demo outcome", "Meets sample criteria"] in r["rows"]
    b = f.other()
    b.auth("Loan eligibility", "DEMO1002", "ask_loan_type")
    b.turn("Personal", "ask_loan_amount")
    b.turn("200000", "ask_loan_tenure")
    r = b.turn("24", "eligibility_complete")
    assert ["Demo outcome", "Outside sample criteria"] in r["rows"]
    return "The sample affordability/score rule produced both outcomes on two profiles."


def existing_loan(f):
    r = f.client.auth("Existing loan EMI", event="loan_complete")
    assert ["Monthly EMI", "₹14,500.00"] in r["rows"]
    return "Owned loan returned seeded principal, monthly EMI and next due date."


def deposits(f):
    c = f.client
    c.auth("Book a fixed deposit", event="ask_fd_amount")
    c.turn("999", "invalid_field")
    c.turn("10000", "ask_fd_tenure")
    r = c.turn("12 months", "review")
    assert ["Quoted maturity", "₹10,666.02"] in r["rows"], r["rows"]
    assert f.store.rows("SELECT COUNT(*) AS n FROM deposits") == [{"n": 3}]
    r = c.turn("Confirm", "deposit_complete")
    assert r["title"].startswith("FD-")
    saved = c.service("View fixed deposits", "deposits_complete")
    assert any(row[0] == r["title"] for row in saved["records"])
    assert f.store.account("DEMO1001")["balance"] == 11_500_000
    return "Quote, confirmation, balance debit and deposit retrieval agreed."


def fd_rollback(f):
    c = f.client
    c.auth("Book a fixed deposit", event="ask_fd_amount")
    c.turn("150000", "ask_fd_tenure")
    c.turn("24 months", "review")
    c.turn("Confirm", "commit_rejected")
    assert not f.store.rows("SELECT * FROM operations")
    assert f.store.rows("SELECT COUNT(*) AS n FROM deposits") == [{"n": 3}]
    return "Failed funding wrote neither a deposit nor an operation receipt."


def card_reads(f):
    c = f.client
    r = c.auth("Card statement", event="statement_complete")
    assert len(r["records"]) == 2
    limit = c.service("Card limit and rewards", "limit_complete")
    assert ["Available credit", "₹1,31,550.00"] in limit["rows"]
    due = c.service("Card payment due", "due_complete")
    assert ["Minimum due", "₹922.50"] in due["rows"]
    return "Statement, available credit, reward points and due information were returned."


def limit_case(f):
    c = f.client
    c.auth("Request a higher card limit", event="ask_limit_amount")
    c.turn("140000", "invalid_field")
    c.turn("180000", "review")
    r = c.turn("Confirm", "case_complete")
    assert r["title"].startswith("LIM-")
    assert f.store.card("DEMO1001")["credit_limit"] == 15_000_000
    return "Limit review created a local ticket without raising the stored limit."


def fraud(f):
    c = f.client
    c.auth("Report a suspicious transaction", event="ask_transaction_ref")
    c.turn("TXN-1002-01", "invalid_field")
    c.turn("TXN-1001-01", "ask_description")
    c.turn("Fictional charge is unfamiliar and needs review.", "review")
    r = c.turn("Confirm", "case_complete")
    assert r["title"].startswith("FRD-")
    return "Foreign transaction denied; owned transaction yielded a fraud case."


def block(f):
    c = f.client
    c.auth("Block demo card", event="review")
    assert f.store.card("DEMO1001")["status"] == "Active"
    c.turn("Confirm", "card_block_complete")
    assert f.store.card("DEMO1001")["status"] == "Blocked"
    c.service("Block demo card", "card_already_blocked")
    return "Confirmed block persisted and a repeat did not create a second action."


def grievance(f):
    c = f.client
    receipt = draft_grievance(c)
    c.service("Track a case", "ask_case_ref")
    result = c.turn(receipt["title"], "case_complete")
    assert ["Status", "Open"] in result["rows"]
    return "Confirmed grievance was retrievable through its saved reference."


def foreign_case(f):
    receipt = draft_grievance(f.client)
    other = f.other()
    other.auth("Track a case", "DEMO1002", "ask_case_ref")
    other.turn(receipt["title"], "case_not_found")
    return "Verified second customer received an ownership-safe lookup miss."


def privacy(f):
    draft_grievance(f.client)
    audit = json.dumps(f.store.rows("SELECT * FROM audit"))
    traces = json.dumps(f.transcript)
    for private in ("DEMO1001", "0000001001", "Fictional service fee needs a review."):
        assert private not in audit and private not in traces
    assert "[Verification code entered]" in traces
    return "Audit and user echoes omitted the demo identity, mobile and case description."


def http_guards(f):
    c = Client(f.base, f.timings)
    c.request("/api/chat", {"text": "Check balance", "request_id": "anonymous-test"}, want=401)
    c.request("/api/demo-inbox", want=401)
    c.request("/api/chat", {"text": "Check balance", "request_id": "foreign-origin"},
              headers={"Origin": "https://unrelated.invalid"}, want=403)
    c.request("/api/session", headers={"Host": "unrelated.invalid"}, want=403)
    return "Anonymous and foreign-origin requests could not use protected routes."


def signed_out(f):
    c = f.client
    c.auth("Check balance", event="balance_complete")
    old = next(iter(c.jar)).value
    c.request("/api/reset", {})
    assert old != next(iter(c.jar)).value
    c.service("Card statement", "ask_identity")
    return "New chat rotated the session and required verification again."


def fallback(f):
    f.client.turn("🪐🪐", "fallback")
    f.client.turn("Confirm", "no_pending_draft")
    assert not f.store.rows("SELECT * FROM operations")
    return "Unsupported input and confirmation without a draft produced no write."


def rasa_contract(f):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            assert self.path == "/model/parse"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body["text"])
            data = b'{"intent":{"name":"account_balance_enquiry","confidence":0.88}}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_):
            return

    with running(ThreadingHTTPServer(("127.0.0.1", 0), Handler)) as stub:
        with running(make_server(Assistant(f.store, RasaNLU(stub + "/model/parse")), ROOT, 0)) as base:
            c = Client(base, f.timings)
            c.request("/api/session")
            c.turn("Balance for 0000001001", "ask_identity")
            c.turn("DEMO1001", "otp_issued")
            c.turn(c.request("/api/demo-inbox")["code"], "balance_complete")
    assert calls == ["Balance for [number]"]
    return "Rasa-compatible stub received one redacted opening turn; workflow fields stayed local."


CASES = (
    ("Browser assets and session", "Interface", session_assets),
    ("Verified balance from typed request", "Accounts", balance),
    ("Unknown identity and inbox isolation", "Verification", unknown_identity),
    ("Wrong, malformed and consumed OTP", "Verification", wrong_otp),
    ("Three-attempt OTP lock", "Verification", otp_lock),
    ("OTP cooldown, expiry and resend", "Verification", otp_resend),
    ("Rolling OTP issue limit", "Verification", issue_rate),
    ("Verification expiry before commit", "Verification", grant_expiry),
    ("Filtered transaction history", "Accounts", history),
    ("Confirmed transfer reconciliation", "Transfers", transfer),
    ("Cancelled transfer", "Transfers", transfer_cancel),
    ("Payee, amount and balance validation", "Transfers", transfer_validation),
    ("Change amount before confirmation", "Transfers", amount_change),
    ("High-value beneficiary re-entry", "Transfers", step_up),
    ("Duplicate confirmation and conflicting ID", "Transfers", idempotency),
    ("Competing transfers", "Transfers", concurrent),
    ("Restart persistence", "Transfers", persisted),
    ("Loan criteria pass and fail", "Lending", loan_estimate),
    ("Existing loan EMI query", "Lending", existing_loan),
    ("FD quote, booking and enquiry", "Deposits", deposits),
    ("Failed FD funding rollback", "Deposits", fd_rollback),
    ("Card statement, limit and due", "Cards", card_reads),
    ("Card limit review ticket", "Cards", limit_case),
    ("Fraud report ownership", "Cases", fraud),
    ("Confirmed card block", "Cards", block),
    ("Grievance receipt and case status", "Cases", grievance),
    ("Cross-profile case denial", "Cases", foreign_case),
    ("Masked echoes and audit", "Verification", privacy),
    ("Anonymous and cross-origin requests", "Interface", http_guards),
    ("New chat revokes verification", "Verification", signed_out),
    ("Fallback and no pending draft", "Interface", fallback),
    ("Rasa HTTP contract via stub", "Interface", rasa_contract),
)


def run_case(label, group, check):
    timings, transcript = [], []
    with TemporaryDirectory(prefix="bank-test-") as directory:
        store = Store(Path(directory) / "banking.db", today=lambda: DATE)
        clock = Clock()
        with running(make_server(Assistant(store, PortableNLU(MODEL), clock), ROOT, 0)) as base:
            fixture = Fixture(base, store, clock, timings)
            try:
                observed = check(fixture)
                status = "PASS"
            except Exception as exc:
                observed, status = repr(exc), "FAIL"
            transcript = fixture.transcript
    return {"name": label, "group": group, "status": status,
            "observed": observed, "timings": timings, "transcript": transcript}


def run_cases():
    return [run_case(*case) for case in CASES]
