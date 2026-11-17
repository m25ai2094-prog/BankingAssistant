"""Start the complete local banking project."""

from argparse import ArgumentParser
from pathlib import Path
import webbrowser

from banking.engine import Assistant
from banking.http_app import make_server
from banking.nlu import PortableNLU, RasaNLU
from banking.store import Store


ROOT = Path(__file__).resolve().parent


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--db", type=Path, default=ROOT / "instance" / "banking_demo.db")
    parser.add_argument("--nlu-url", help="Optional loopback Rasa /model/parse endpoint")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    args = parser.parse_args()
    model = RasaNLU(args.nlu_url) if args.nlu_url else PortableNLU(ROOT / "models" / "bank_intents.json")
    try:
        with make_server(Assistant(Store(args.db), model), ROOT, args.port) as server:
            url = f"http://127.0.0.1:{server.server_port}"
            print(f"Banking Assistant ready at {url}", flush=True)
            print(f"NLU: {model.name}. All records and actions are fictional.", flush=True)
            print("Keep this window open. Press Ctrl+C to stop.", flush=True)
            if args.open:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nBanking Assistant stopped.")
    except OSError as exc:
        parser.exit(1, f"Unable to start the local server: {exc}. Try --port 8788 if the port is busy.\n")


if __name__ == "__main__":
    main()
