"""Render entry point for the Banking Assistant synthetic demo."""

import os
from pathlib import Path

from banking.engine import Assistant
from banking.http_app import make_server
from banking.nlu import PortableNLU
from banking.store import Store


ROOT = Path(__file__).resolve().parent


def main():
    port = int(os.environ.get("PORT", "8787"))
    database = Path(os.environ.get("BANKING_DB_PATH", "/tmp/banking_assistant_demo.sqlite3"))
    allowed_hosts = os.environ.get(
        "BANKING_ALLOWED_HOSTS",
        "banking-assistant-demo.onrender.com,localhost,127.0.0.1",
    ).split(",")

    model = PortableNLU(ROOT / "models" / "bank_intents.json")
    assistant = Assistant(Store(database), model)
    server = make_server(
        assistant,
        ROOT,
        port=port,
        host="0.0.0.0",
        allowed_hosts=allowed_hosts,
    )
    print(f"Banking Assistant ready on 0.0.0.0:{server.server_port}", flush=True)
    print(f"NLU: {model.name}. All accounts and actions are fictional demo data.", flush=True)
    print(f"Database: {database} (ephemeral cloud storage)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Banking Assistant stopped.", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
