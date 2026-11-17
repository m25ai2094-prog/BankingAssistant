"""SQLite sandbox with ownership checks and idempotent atomic writes."""

from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import sqlite3

from .catalog import DEMO_IDENTITIES, FD_RATES, RAILS, STEP_UP, TRANSFER_MAX
from .money import add_months, deposit_maturity, inr


SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, mobile TEXT NOT NULL UNIQUE,
  income INTEGER NOT NULL, obligations INTEGER NOT NULL, score INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts(
  id TEXT PRIMARY KEY, customer_id TEXT UNIQUE NOT NULL REFERENCES customers(id),
  kind TEXT NOT NULL, balance INTEGER NOT NULL CHECK(balance >= 0),
  held INTEGER NOT NULL DEFAULT 0 CHECK(held >= 0 AND held <= balance)
);
CREATE TABLE IF NOT EXISTS beneficiaries(
  owner TEXT NOT NULL REFERENCES customers(id), target TEXT NOT NULL REFERENCES accounts(id),
  alias TEXT NOT NULL, ifsc TEXT NOT NULL, PRIMARY KEY(owner, target), UNIQUE(owner, alias)
);
CREATE TABLE IF NOT EXISTS ledger(
  reference TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
  amount INTEGER NOT NULL CHECK(amount <> 0), kind TEXT NOT NULL,
  note TEXT NOT NULL, day TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ledger_account_day ON ledger(account_id, day DESC, reference DESC);
CREATE TABLE IF NOT EXISTS transfers(
  reference TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES accounts(id),
  destination TEXT NOT NULL REFERENCES accounts(id), amount INTEGER NOT NULL CHECK(amount > 0),
  rail TEXT NOT NULL, purpose TEXT NOT NULL, day TEXT NOT NULL, CHECK(source <> destination)
);
CREATE TABLE IF NOT EXISTS loans(
  reference TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
  product TEXT NOT NULL, outstanding INTEGER NOT NULL, emi INTEGER NOT NULL, due TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deposits(
  reference TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
  principal INTEGER NOT NULL CHECK(principal > 0), months INTEGER NOT NULL,
  rate TEXT NOT NULL, maturity INTEGER NOT NULL, maturity_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards(
  customer_id TEXT PRIMARY KEY REFERENCES customers(id), last4 TEXT NOT NULL,
  credit_limit INTEGER NOT NULL, outstanding INTEGER NOT NULL, minimum_due INTEGER NOT NULL,
  due TEXT NOT NULL, rewards INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('Active','Blocked'))
);
CREATE TABLE IF NOT EXISTS card_entries(
  id TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES cards(customer_id),
  day TEXT NOT NULL, merchant TEXT NOT NULL, amount INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cases(
  reference TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
  kind TEXT NOT NULL, subject TEXT NOT NULL, description TEXT NOT NULL,
  contact TEXT NOT NULL, status TEXT NOT NULL, opened TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS cases_owner ON cases(customer_id, reference);
CREATE TABLE IF NOT EXISTS operations(
  token TEXT PRIMARY KEY, customer_id TEXT NOT NULL REFERENCES customers(id),
  kind TEXT NOT NULL, response_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, session_tag TEXT NOT NULL, event TEXT NOT NULL,
  reference TEXT, utc TEXT NOT NULL
);
"""


class BusinessError(ValueError):
    """A rejected business operation with a user-readable reason."""


class Store:
    def __init__(self, path: Path, today=date.today):
        self.path = Path(path)
        self.today = today
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
        with self.write() as db:
            if db.execute("SELECT 1 FROM customers LIMIT 1").fetchone() is None:
                self.seed(db)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @contextmanager
    def write(self):
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def seed(self, db):
        today = self.today()
        for index, record in enumerate(DEMO_IDENTITIES, 1):
            cid, aid = record["id"], record["account"]
            db.execute("INSERT INTO customers VALUES (?,?,?,?,?,?)",
                       (cid, record["name"], record["mobile"], record["income"],
                        record["obligations"], record["score"]))
            db.execute("INSERT INTO accounts VALUES (?,?,?,?,?)", (aid, cid, "Savings", record["balance"], 0))
            entries = [(-72_500, "Debit", "Demo grocery"), (2_550_000, "Credit", "Demo salary"),
                       (-340_000, "Debit", "Demo utilities"), (-180_000, "Debit", "Demo retail"),
                       (550_000, "Credit", "Demo refund")]
            for j, ((amount, kind, note), age) in enumerate(zip(entries, (1, 3, 7, 17, 40)), 1):
                db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?)",
                           (f"TXN-{cid[-4:]}-{j:02d}", aid, amount, kind, note, (today - timedelta(days=age)).isoformat()))
            db.execute("INSERT INTO loans VALUES (?,?,?,?,?,?)",
                       (f"LN-{cid[-4:]}", cid, ("Home", "Personal", "Auto")[index - 1],
                        (124_000_000, 18_000_000, 25_000_000)[index - 1],
                        record["obligations"], (today + timedelta(days=12)).isoformat()))
            principal = index * 2_500_000
            db.execute("INSERT INTO deposits VALUES (?,?,?,?,?,?,?)",
                       (f"FD-SEED-{cid[-4:]}", cid, principal, 12, str(FD_RATES[12]),
                        deposit_maturity(principal, FD_RATES[12], 12), add_months(today, 8).isoformat()))
            db.execute("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?)",
                       (cid, record["card"], 15_000_000, 1_845_000, 92_250,
                        (today + timedelta(days=17)).isoformat(), index * 1400, "Active"))
            for j, (merchant, amount) in enumerate((("Demo electronics", 1_400_000),
                                                    ("Demo supermarket", 445_000)), 1):
                db.execute("INSERT INTO card_entries VALUES (?,?,?,?,?)",
                           (f"CARD-{cid[-4:]}-{j}", cid, (today - timedelta(days=j + 3)).isoformat(),
                            merchant, amount))
        for owner in DEMO_IDENTITIES:
            for payee in DEMO_IDENTITIES:
                if owner["id"] != payee["id"]:
                    db.execute("INSERT INTO beneficiaries VALUES (?,?,?,?)",
                               (owner["id"], payee["account"], payee["name"], "DEMO0" + payee["account"][-4:] + "00"))

    def rows(self, query, *parameters):
        with closing(self.connect()) as db:
            return [dict(row) for row in db.execute(query, parameters)]

    def customer(self, identity):
        rows = self.rows("SELECT * FROM customers WHERE id=? OR mobile=?", identity.upper(), identity)
        return rows[0] if rows else None

    def account(self, customer):
        return self.rows("SELECT * FROM accounts WHERE customer_id=?", customer)[0]

    def payees(self, customer):
        return self.rows("SELECT alias,target,ifsc FROM beneficiaries WHERE owner=? ORDER BY alias", customer)

    def history(self, customer, days, direction="All", minimum=0):
        start = (self.today() - timedelta(days=days - 1)).isoformat()
        return self.rows(
            """SELECT l.reference,l.day,l.kind,l.amount,l.note FROM ledger l JOIN accounts a ON l.account_id=a.id
               WHERE a.customer_id=? AND l.day>=? AND (?='All' OR l.kind=?) AND abs(l.amount)>=?
               ORDER BY l.day DESC,l.reference DESC LIMIT 12""", customer, start, direction, direction, minimum)

    def transaction(self, customer, reference):
        rows = self.rows("""SELECT l.reference,l.amount,l.day FROM ledger l JOIN accounts a ON l.account_id=a.id
                            WHERE a.customer_id=? AND l.reference=?""", customer, reference)
        return rows[0] if rows else None

    def loan(self, customer):
        return self.rows("SELECT * FROM loans WHERE customer_id=? ORDER BY reference", customer)[0]

    def deposits(self, customer):
        return self.rows("SELECT * FROM deposits WHERE customer_id=? ORDER BY maturity_date,reference LIMIT 12", customer)

    def card(self, customer):
        return self.rows("SELECT * FROM cards WHERE customer_id=?", customer)[0]

    def statement(self, customer):
        return self.rows("SELECT day,merchant,amount FROM card_entries WHERE customer_id=? ORDER BY day DESC", customer)

    def case(self, customer, reference):
        rows = self.rows("SELECT * FROM cases WHERE customer_id=? AND reference=?", customer, reference)
        return rows[0] if rows else None

    @staticmethod
    def audit(db, tag, event, reference=None):
        db.execute("INSERT INTO audit(session_tag,event,reference,utc) VALUES (?,?,?,?)",
                   (tag, event, reference, datetime.now(timezone.utc).isoformat(timespec="seconds")))

    def event(self, tag, event):
        with self.write() as db:
            self.audit(db, tag, event)

    def commit(self, customer, token, kind, fields, tag):
        with self.write() as db:
            prior = db.execute("SELECT * FROM operations WHERE token=?", (token,)).fetchone()
            if prior:
                if prior["customer_id"] != customer or prior["kind"] != kind:
                    raise BusinessError("This draft cannot be reused.")
                return json.loads(prior["response_json"])
            handler = {"transfer": self.transfer, "deposit": self.deposit,
                       "card_block": self.block_card, "case": self.create_case}[kind]
            result = handler(db, customer, fields)
            db.execute("INSERT INTO operations VALUES (?,?,?,?)", (token, customer, kind, json.dumps(result)))
            self.audit(db, tag, kind + "_committed", result["reference"])
            return result

    def debit(self, db, customer, amount):
        account = db.execute("SELECT id FROM accounts WHERE customer_id=?", (customer,)).fetchone()
        changed = db.execute("UPDATE accounts SET balance=balance-? WHERE id=? AND balance-held>=?",
                             (amount, account["id"], amount))
        if changed.rowcount != 1:
            raise BusinessError("Insufficient available demo balance.")
        return account["id"]

    def transfer(self, db, customer, fields):
        amount = fields["amount"]
        payee = db.execute("SELECT * FROM beneficiaries WHERE owner=? AND target=?",
                           (customer, fields["target"])).fetchone()
        if payee is None or fields["rail"] not in RAILS or not 0 < amount <= TRANSFER_MAX:
            raise BusinessError("Check the registered payee, amount and demo rail.")
        if amount >= STEP_UP and fields.get("payee_check") != payee["target"][-4:]:
            raise BusinessError("The beneficiary suffix check is required.")
        reference = "TRF-" + secrets.token_hex(5).upper()
        day = self.today().isoformat()
        source = self.debit(db, customer, amount)
        db.execute("UPDATE accounts SET balance=balance+? WHERE id=?", (amount, payee["target"]))
        db.execute("INSERT INTO transfers VALUES (?,?,?,?,?,?,?)",
                   (reference, source, payee["target"], amount, fields["rail"], fields["purpose"], day))
        db.executemany("INSERT INTO ledger VALUES (?,?,?,?,?,?)", (
            (reference + "-D", source, -amount, "Debit", "Demo transfer sent", day),
            (reference + "-C", payee["target"], amount, "Credit", "Demo transfer received", day),
        ))
        return {"reference": reference, "status": "Recorded in sandbox",
                "rows": [["Beneficiary", payee["alias"]], ["Amount", inr(amount)], ["Demo rail", fields["rail"]]]}

    def deposit(self, db, customer, fields):
        amount, months = fields["amount"], fields["months"]
        if months not in FD_RATES or not 100_000 <= amount <= TRANSFER_MAX:
            raise BusinessError("Choose a supported tenure and an amount between ₹1,000 and ₹5,00,000.")
        rate = FD_RATES[months]
        maturity = deposit_maturity(amount, rate, months)
        maturity_date = add_months(self.today(), months).isoformat()
        reference = "FD-" + secrets.token_hex(5).upper()
        account = self.debit(db, customer, amount)
        db.execute("INSERT INTO deposits VALUES (?,?,?,?,?,?,?)",
                   (reference, customer, amount, months, str(rate), maturity, maturity_date))
        db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?)", (reference, account, -amount, "Debit",
                   "Demo fixed deposit booked", self.today().isoformat()))
        return {"reference": reference, "status": "Booked in sandbox",
                "rows": [["Principal", inr(amount)], ["Maturity", inr(maturity)], ["Maturity date", maturity_date]]}

    def block_card(self, db, customer, fields):
        row = db.execute("SELECT * FROM cards WHERE customer_id=?", (customer,)).fetchone()
        if row is None or fields["last4"] != row["last4"]:
            raise BusinessError("The selected card belongs to a different profile.")
        if row["status"] == "Blocked":
            raise BusinessError("This demo card is already blocked.")
        db.execute("UPDATE cards SET status='Blocked' WHERE customer_id=?", (customer,))
        return {"reference": "BLK-" + secrets.token_hex(5).upper(), "status": "Blocked in sandbox",
                "rows": [["Card", "•••• " + row["last4"]]]}

    def create_case(self, db, customer, fields):
        kind, subject = fields["kind"], fields["subject"]
        if kind == "Fraud alert":
            owned = db.execute("""SELECT 1 FROM ledger l JOIN accounts a ON l.account_id=a.id
                                  WHERE a.customer_id=? AND l.reference=?""", (customer, subject)).fetchone()
            if not owned:
                raise BusinessError("Choose a transaction belonging to this profile.")
        reference = {"Fraud alert": "FRD-", "Grievance": "GRV-", "Limit review": "LIM-"}[kind] + secrets.token_hex(5).upper()
        db.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?,?)",
                   (reference, customer, kind, subject, fields.get("description", ""),
                    fields.get("contact", "In-app"), "Open", self.today().isoformat()))
        return {"reference": reference, "status": "Open",
                "rows": [["Case type", kind], ["Subject", subject], ["Target", "2 working days (demo)"]]}
