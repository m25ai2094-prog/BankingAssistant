"""Session-bound, single-use OTP for synthetic accounts and an in-app demo inbox."""

from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256
import hmac
import re
import secrets
from threading import RLock
from time import monotonic


OTP_TTL = 300
GRANT_TTL = 600
SESSION_TTL = 1800
RESEND_DELAY = 15
OTP_ATTEMPTS = 3
OTP_ISSUES = 4


@dataclass
class Challenge:
    identifier: str
    customer_id: str | None
    digest: bytes
    issued_at: float
    delivery: str | None


@dataclass
class Draft:
    intent: str
    step: str
    token: str = field(default_factory=lambda: secrets.token_hex(16))
    fields: dict = field(default_factory=dict)
    review: dict | None = None


@dataclass
class Session:
    key: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    lock: RLock = field(default_factory=RLock)
    draft: Draft | None = None
    challenge: Challenge | None = None
    customer_id: str | None = None
    verified_until: float = 0
    last_activity: float = 0
    failed: int = 0
    locked_until: float = 0
    issues: deque = field(default_factory=deque)
    cache: dict = field(default_factory=dict)
    closed: bool = False

    @property
    def tag(self) -> str:
        return sha256(self.key.encode()).hexdigest()[:16]


class Authentication:
    def __init__(self, clock=monotonic):
        self.clock = clock
        self.secret = secrets.token_bytes(32)

    def digest(self, session: Session, identifier: str, code: str) -> bytes:
        payload = f"{session.key}:{identifier}:{code}".encode()
        return hmac.digest(self.secret, payload, "sha256")

    def issue(self, session: Session, customer_id: str | None) -> str:
        now = self.clock()
        if now < session.locked_until:
            return "otp_locked"
        if session.locked_until:
            session.failed = 0
            session.locked_until = 0
        if session.challenge and now - session.challenge.issued_at < RESEND_DELAY:
            return "otp_cooldown"
        while session.issues and now - session.issues[0] >= OTP_TTL:
            session.issues.popleft()
        if len(session.issues) >= OTP_ISSUES:
            return "otp_rate_limited"
        code = f"{secrets.randbelow(1_000_000):06d}"
        identifier = secrets.token_hex(16)
        session.challenge = Challenge(identifier, customer_id, self.digest(session, identifier, code),
                                      now, code if customer_id else None)
        session.issues.append(now)
        return "otp_issued"

    def inbox(self, session: Session) -> dict:
        challenge = session.challenge
        if challenge and self.clock() - challenge.issued_at < OTP_TTL:
            remaining = int(OTP_TTL - (self.clock() - challenge.issued_at))
            return {"code": challenge.delivery, "remaining": max(0, remaining)}
        return {"code": None, "remaining": 0}

    def verify(self, session: Session, text: str) -> str:
        challenge = session.challenge
        if challenge is None or self.clock() - challenge.issued_at >= OTP_TTL:
            return "otp_expired"
        if not re.fullmatch(r"[0-9]{6}", text):
            return "otp_format"
        valid = hmac.compare_digest(self.digest(session, challenge.identifier, text), challenge.digest)
        if valid and challenge.customer_id:
            session.customer_id = challenge.customer_id
            session.verified_until = self.clock() + GRANT_TTL
            session.failed = 0
            session.challenge = None
            return "verified"
        session.failed += 1
        if session.failed >= OTP_ATTEMPTS:
            session.challenge = None
            session.draft = None
            session.locked_until = self.clock() + OTP_TTL
            return "otp_locked"
        return "otp_rejected"

    def authorized(self, session: Session) -> bool:
        return session.customer_id is not None and self.clock() < session.verified_until

    def clear_identity(self, session: Session):
        session.customer_id = None
        session.verified_until = 0
        session.challenge = None
