# Deploy Banking Assistant on Render Free

This deployment uses the bundled portable TF-IDF + logistic-regression intent classifier and the existing deterministic banking workflow engine. It does **not** start Rasa or install the optional Rasa/training dependencies.

## Deploy

1. Push this repository to GitHub.
2. In Render, choose **New → Blueprint** and select this repository's `main` branch.
3. Keep the Blueprint path at the repository root (`render.yaml`).
4. Review the `banking-assistant-demo` service and choose the Free plan.
5. Deploy the Blueprint.

Render runs:

- Build: `pip install -r requirements-cloud.txt`
- Start: `python cloud_run.py`
- Health check: `/api/health`

The server binds to `0.0.0.0` and uses Render's `PORT`. The host allow-list includes the configured `banking-assistant-demo.onrender.com` hostname and loopback hosts for platform health checks.

## Demo-only limitations

- All customer profiles, balances, beneficiaries, cards, OTPs and banking actions are fictional. Do not enter real customer information or connect this demo to a real bank.
- Render Free has an ephemeral filesystem. The SQLite database is stored under `/tmp`; confirmed demo actions may be reset after a restart, redeploy or instance replacement.
- Free web services can spin down after inactivity, so the first request after idle time may be delayed.
- The in-memory chat sessions and OTP inbox are temporary and may be lost when the service restarts.
- The bundled classifier and all business workflows are retained. The optional Rasa 3.6.21 adapter is for local experimentation only and is not used in this cloud deployment.

## Local use

The original `python run.py --open` launcher and local SQLite persistence remain available. The cloud changes only add an alternate entry point and allow the HTTP server to bind to a configured interface and host allow-list.
