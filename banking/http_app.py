"""Same-origin HTTP interface for local and cloud-hosted banking demos."""

from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
from urllib.parse import urlsplit

from .catalog import DEMO_IDENTITIES, SERVICES
from .engine import ClientError, reply, welcome
from .nlu import NLUUnavailable


COOKIE = "bank_demo_sid"
ASSETS = {"/": ("index.html", "text/html"), "/assets/style.css": ("style.css", "text/css"),
          "/assets/app.js": ("app.js", "text/javascript")}
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


def make_server(assistant, root, port=8787, host="127.0.0.1", allowed_hosts=None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "BankingSandbox/1.0"

        def setup(self):
            super().setup()
            self.connection.settimeout(12)

        def log_message(self, *_):
            # The application records safe business events. HTTP request text is omitted.
            return

        def same_origin(self):
            request_host = self.headers.get("Host", "").strip().lower()
            if not request_host:
                return False
            try:
                host_name = urlsplit("//" + request_host).hostname
            except ValueError:
                return False
            loopback_with_port = host_name in {"localhost", "127.0.0.1"} and host_name in self.server.allowed_hosts
            if request_host not in self.server.allowed_hosts and not loopback_with_port:
                return False
            origin = self.headers.get("Origin")
            if origin is None:
                return True
            try:
                parsed = urlsplit(origin)
            except ValueError:
                return False
            return (parsed.scheme in {"http", "https"} and parsed.netloc.lower() == request_host
                    and not parsed.username and not parsed.password
                    and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)

        def respond(self, status, data, media="application/json", session=None):
            self.send_response(status)
            self.send_header("Content-Type", media + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            if session:
                secure = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
                self.send_header("Set-Cookie",
                                 f"{COOKIE}={session.key}; Path=/; HttpOnly; SameSite=Strict{secure}")
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, status, payload, session=None):
            self.respond(status, json.dumps(payload, ensure_ascii=False).encode(), session=session)

        def current(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
            except ValueError:
                return None
            return assistant.session(cookie[COOKIE].value) if COOKIE in cookie else None

        @staticmethod
        def session_payload(session):
            with session.lock:
                last = next(reversed(session.cache.values()))[1] if session.cache else welcome()
                verified = assistant.auth.authorized(session)
                if last.get("verified") and not verified:
                    last = (reply("Verification expired. Cancel this draft or start a new chat.",
                                  "verification_expired", ("Cancel",)) if session.draft else welcome())
                last = {**last, "verified": verified,
                        "step": session.draft.step if session.draft else "menu"}
                active = next((record for record in DEMO_IDENTITIES
                               if verified and record["id"] == session.customer_id), None)
                return {
                    "reply": last,
                    "model": assistant.model.name,
                    "review": session.draft.review if verified and session.draft and session.draft.step == "confirm" else None,
                    "active_profile": {"id": active["id"], "name": active["name"],
                                       "suffix": active["account"][-4:]} if active else None,
                    "demo_records": [{key: record[key] for key in ("id", "mobile", "name", "account", "card")}
                                     for record in DEMO_IDENTITIES],
                    "services": SERVICES,
                }

        def do_GET(self):
            if not self.same_origin():
                self.send_json(403, {"error": "Open this app using its assigned public URL."})
                return
            path = urlsplit(self.path).path
            if path in ASSETS:
                name, media = ASSETS[path]
                self.respond(200, (root / "static" / name).read_bytes(), media)
                return
            if path == "/api/health":
                self.send_json(200, {"status": "ready", "model": assistant.model.name, "mode": "synthetic sandbox"})
                return
            if path == "/api/session":
                try:
                    session = self.current() or assistant.start()
                    self.send_json(200, self.session_payload(session), session=session)
                except ClientError as exc:
                    self.send_json(503, {"error": str(exc)})
                return
            if path == "/api/demo-inbox":
                session = self.current()
                if session is None:
                    self.send_json(401, {"error": "Start or refresh the chat."})
                    return
                with session.lock:
                    self.send_json(200, assistant.auth.inbox(session))
                return
            if path == "/api/results":
                evidence = root / "evidence" / "summary.json"
                self.send_json(200, json.loads(evidence.read_text(encoding="utf-8")) if evidence.exists() else {})
                return
            self.send_json(404, {"error": "This route is unavailable."})

        def do_POST(self):
            if not self.same_origin():
                self.send_json(403, {"error": "The request origin must match the local app."})
                return
            path = urlsplit(self.path).path
            if path not in {"/api/reset", "/api/chat"}:
                self.send_json(404, {"error": "This route is unavailable."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get_content_type() != "application/json" or not 0 < length <= 8192:
                    self.close_connection = True
                    raise ClientError("Send a JSON request between 1 and 8192 bytes.")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ClientError("Send a JSON object.")
                current = self.current()
                if path == "/api/reset":
                    session = assistant.reset(current)
                    self.send_json(200, self.session_payload(session), session=session)
                    return
                if current is None:
                    self.send_json(401, {"error": "The session expired. Select New chat."})
                    return
                result = assistant.send(current, body.get("text"), body.get("request_id"), body.get("shortcut"))
                self.send_json(200, result)
            except NLUUnavailable as exc:
                self.send_json(503, {"error": str(exc)})
            except sqlite3.OperationalError:
                self.send_json(503, {"error": "The local register is busy. Retry this message."})
            except (ValueError, UnicodeError) as exc:
                message = str(exc) if isinstance(exc, ClientError) else "The request body is invalid."
                self.send_json(400, {"error": message})

    server = ThreadingHTTPServer((host, port), Handler)
    if allowed_hosts is None:
        actual = server.server_port
        server.allowed_hosts = {f"127.0.0.1:{actual}", f"localhost:{actual}"}
        if actual == 80:
            server.allowed_hosts.update({"127.0.0.1", "localhost"})
    else:
        server.allowed_hosts = {item.strip().lower() for item in allowed_hosts if item.strip()}
    return server
