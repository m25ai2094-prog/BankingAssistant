# Banking Assistant

**Rakesh Jaiswal · M25AI2156 · M.Tech. (Artificial Intelligence), IIT Jodhpur**

This project implements a local banking service desk with fictional customers, accounts, deposits, loans, cards and case records. The portable build uses a bundled intent classifier and a deterministic banking workflow engine. An optional Rasa 3.6 NLU adapter uses the same workflow engine and SQLite data.

## Run the complete sandbox

1. Extract the ZIP or RAR into a writable folder.
2. Open the **Banking_Assistant** folder. On Windows, double-click **Start_Banking_Assistant.bat** to start the server and open the dashboard in your default browser. To start it from PowerShell in the project folder, run:

   ```powershell
   py -3 run.py --open
   ```

   On macOS or Linux, use `python3 run.py --open`. The default build needs Python 3.10 or newer and its standard library. The trained model is included.
3. Leave the terminal open. If the browser is closed, open **http://127.0.0.1:8787** manually.
4. Press **Ctrl+C** in the terminal to stop the server. Reopening the app preserves confirmed sandbox actions in `instance/banking_demo.db`.

If the port is in use, run `py -3 run.py --port 8788 --open`. To start a separate demonstration with the opening balances, run `py -3 run.py --db instance/presentation.db --open`. Choose a fresh filename for a fresh sandbox.

## Explore the dashboard

**Overview** lists all 15 services, with filters for **Accounts**, **Transfers**, **Loans & deposits**, **Cards** and **Support**. The **Demo profile** card selects a fictional customer and offers a balance check. A protected read or action opens the same verification workflow.

Choose a service card or open **Assistant** to type a request. The current request panel shows your progress and the conversation offers choices for the current step. **Overview → Resume request** returns to a draft in the same browser session. **Switch profile** and **New chat** clear the verification grant and discard any draft.

## Demonstrate a transfer

1. From **Overview**, click **Transfer money**. To exercise the opening intent model, open **Assistant** and type “Send money to a beneficiary” in a fresh conversation.
2. Select Aarav Mehta in **Demo records** and click **Use DEMO1001**, or type **DEMO1001**. Click the current six-digit code in **Demo inbox** beside the message box.
3. Choose **Meera Rao**, enter **1500**, choose **IMPS**, and choose **Personal**.
4. Check the beneficiary, amount, rail and purpose in the review. Click **Confirm** and keep the `TRF-` receipt. **Check balance** should show **₹1,23,500.00** when this is the first confirmed action from a fresh sandbox.
5. Try **Transaction history → 7 days → Debit → Any amount** to find the saved debit. Use **Overview → Switch profile**, select **DEMO1002**, and choose **Verify & check balance** to see **₹69,500.00**. Use **Transaction history** to find the corresponding credit.

Choose a fresh sandbox when a previous transfer or fixed deposit has changed the expected opening balance. A transfer at **₹25,000** or higher asks for the beneficiary suffix before review. Meera's demo account ends in **2002**. **Change amount** returns to entry and asks for rail and purpose again before generating a fresh review. **Cancel** discards the pending draft.

## Other walkthroughs

| Service | Sample sequence after verification |
| --- | --- |
| Balance | Check balance shows ledger and available balances for the verified account. |
| History | Select 30 days, Debit, and minimum 1500 to filter the seeded records. |
| Loan eligibility | Personal, 200000, 24 months. Compare DEMO1001 and DEMO1002. |
| Existing loan EMI | Read outstanding principal, EMI and next due date. |
| Fixed deposits | Book 10000 for 12 months, review the quarterly-compounded quote, confirm, then view fixed deposits. |
| Credit card | Open card statement, card limit and rewards, or card payment due under Cards. |
| Limit review | Enter 180000 and confirm. Track the resulting LIM reference. |
| Fraud | Use TXN-1001-01 with DEMO1001, enter a fictional description and confirm. |
| Card block | Review and confirm the masked demo card. A second request reports its saved status. |
| Grievance | Charges, “Fictional service fee needs a review.”, In-app, Confirm. Track the GRV receipt. |

The demo identities are DEMO1001, DEMO1002 and DEMO1003. Their fictional mobile numbers are 0000001001, 0000001002 and 0000001003. All service screens use demo data. The four rail names label local ledger simulations. The inbox displays a synthetic OTP in the current browser session.

## Verify the project

```powershell
py -3 -m unittest discover -v
py -3 evaluate.py --out evidence/recheck
```

The standard-library evaluator scores the shipped model on the separate authored holdout, then exercises the loopback HTTP server against temporary databases. The saved evidence includes one row per prediction and HTTP turn. The supplied evaluation plots use that saved evidence. `evidence/browser_walkthrough.md` records the separate browser check and identifies the interface screenshots. Running a new evaluation into `evidence/recheck` preserves the original run. Local timing changes with the environment.

To retrain, use a separate Python 3.11 or 3.12 environment with `requirements-training.txt`:

```powershell
py -3.12 -m venv .train-venv
.\.train-venv\Scripts\python.exe -m pip install -r requirements-training.txt
.\.train-venv\Scripts\python.exe train.py
.\.train-venv\Scripts\python.exe evaluate.py
.\.train-venv\Scripts\python.exe tools\plot_results.py
```

The plot script requires Graphviz `dot` on PATH for the three diagrams. Retraining exports model coefficients and the matching Rasa training YAML. Training uses only `corpus/train.txt` and its folds. `corpus/heldout.txt` is used for final evaluation.

## Optional Rasa 3.6 DIET mode

Use a separate **64-bit Python 3.10** environment for the pinned Rasa release. In PowerShell:

```powershell
py -3.10 -m venv .rasa-venv
.\.rasa-venv\Scripts\python.exe -m pip install -r requirements-rasa.txt
.\.rasa-venv\Scripts\python.exe -m rasa train nlu --config rasa/config.yml --nlu rasa/data/nlu.yml --out rasa/models --fixed-model-name banking-nlu
.\.rasa-venv\Scripts\python.exe -m rasa run --enable-api -i 127.0.0.1 -p 5005 -m rasa/models/banking-nlu.tar.gz
```

In a second terminal, from the project folder:

```powershell
py -3 run.py --nlu-url http://127.0.0.1:5005/model/parse
```

Type an opening request to exercise the connector. Protected slot collection continues in Python. The saved report measures the portable model and the local HTTP workflow path. The automated Rasa connector check used a local contract stub. A separately trained DIET run requires its own evaluation. See `rasa_pro_reference/README.md` for the earlier CALM transfer demonstration.

## Free cloud deployment (Render)

The repository includes a lightweight Render Blueprint in `render.yaml`. It runs `cloud_run.py` with the bundled portable TF-IDF + logistic-regression classifier and the same deterministic banking workflow engine. It does not install or start the optional Rasa service. See `DEPLOY_RENDER.md` for deployment steps and demo-only limitations.

Render Free uses ephemeral storage: the SQLite demo register is stored under `/tmp`, and confirmed demo changes may reset after a restart or redeploy. All records and transactions are fictional; never enter real banking or customer data.

## Source map

| Path | Role |
| --- | --- |
| `run.py`, `Start_Banking_Assistant.bat` | Portable startup and local command options |
| `banking/catalog.py`, `banking/money.py` | Service catalogue, fixtures, integer-paise parsing, EMI and FD calculations |
| `banking/auth.py` | Session-bound demo challenge, verification window, cooldown and attempt limits |
| `banking/engine.py` | State transitions, protected reads, review and confirmation |
| `banking/store.py` | SQLite schema, seed records, ownership, atomic write and audit |
| `banking/http_app.py`, `static/` | HTTP session boundary, browser interface and trace |
| `banking/nlu.py`, `train.py`, `models/`, `corpus/` | Portable inference, training and data |
| `rasa/` | Optional DIET configuration and generated training split |
| `rasa_pro_reference/` | Earlier CALM transfer example and component validation |
| `tests/`, `evaluate.py`, `evidence/` | Runnable checks, raw results and transcripts |
| `tools/`, `figures/` | Plotting and diagram sources with generated outputs |

## Model and operational boundaries

The sample corpus is authored English, with 20 labels. Classifier scores describe the supplied data. Financial calculations apply illustrative product rates and criteria. The service binds to IPv4 loopback and stores demo state on the local computer. A deployment connected to actual banking services would require institutional approval, independent security review, a separate authentication channel and audited service integrations.
