"""Regenerate project figures from the saved evaluation and diagram sources."""

import csv
from collections import Counter
import json
from pathlib import Path
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence"
FIGURES = ROOT / "figures"
TEAL = "#17695e"
NAVY = "#17324e"
GRAY = "#617184"

SHORT = {
    "account_balance_enquiry": "Account balance", "affirm": "Affirm", "block_card_request": "Card block",
    "case_status_request": "Case status", "credit_card_limit_enhancement": "Limit enhancement",
    "credit_card_limit_enquiry": "Card limit", "credit_card_payment_due_enquiry": "Card payment due",
    "credit_card_statement_request": "Card statement", "deny": "Deny", "fixed_deposit_booking": "FD booking",
    "fixed_deposit_enquiry": "FD enquiry", "fraud_alert_report": "Fraud report", "fund_transfer_initiation": "Fund transfer",
    "goodbye": "Goodbye", "greet": "Greeting", "grievance_registration": "Grievance",
    "loan_eligibility_enquiry": "Loan eligibility", "loan_emi_query": "Loan EMI",
    "out_of_scope": "Out of scope", "transaction_history_request": "Transaction history",
}


def save(fig, name):
    fig.savefig(FIGURES / name, dpi=220, bbox_inches="tight", facecolor="white", pad_inches=.14)
    plt.close(fig)


def main():
    FIGURES.mkdir(exist_ok=True)
    data = json.loads((EVIDENCE / "summary.json").read_text(encoding="utf-8"))
    classes = data["classes"]
    codes = [f"I{i:02d}" for i in range(1, len(classes) + 1)]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "text.color": NAVY, "axes.labelcolor": NAVY,
                         "xtick.color": GRAY, "ytick.color": GRAY, "axes.titleweight": "bold"})

    matrix = np.array(data["nlu"]["matrix"])
    fig, ax = plt.subplots(figsize=(8.4, 6.7))
    im = ax.imshow(matrix, vmin=0, vmax=8, cmap="GnBu")
    ax.set(xticks=range(20), xticklabels=codes, yticks=range(20), yticklabels=codes,
           xlabel="Predicted intent", ylabel="Expected intent", title="Held-out confusion matrix")
    plt.setp(ax.get_xticklabels(), rotation=60, ha="right")
    for i, j in np.argwhere(matrix > 0):
        ax.text(j, i, str(matrix[i, j]), ha="center", va="center", fontsize=8,
                color="white" if matrix[i, j] > 4 else NAVY)
    fig.colorbar(im, ax=ax, shrink=.7, label="Utterances")
    save(fig, "confusion_matrix.png")

    rows = data["nlu"]["by_intent"]
    order = sorted(rows, key=lambda row: (row["f1"], SHORT[row["intent"]]), reverse=True)
    fig, ax = plt.subplots(figsize=(8.5, 6.7))
    names = [SHORT[row["intent"]] for row in order]
    bars = ax.barh(names, [row["f1"] for row in order], color=[TEAL if row["f1"] >= .9 else "#a78754" for row in order])
    ax.invert_yaxis()
    ax.set(xlim=(0, 1.1), xlabel="F1 score", title="F1 by intent on the authored holdout")
    ax.grid(axis="x", color="#e3eaed")
    ax.set_axisbelow(True)
    ax.bar_label(bars, fmt="%.2f", padding=3, fontsize=8)
    save(fig, "intent_f1.png")

    fig, ax = plt.subplots(figsize=(8.4, 3.7))
    names = ["Word + character", "Word unigram baseline"]
    x = np.arange(2)
    acc = [data["nlu"]["accuracy"] * 100, data["baseline"]["accuracy"] * 100]
    f1 = [data["nlu"]["macro_f1"] * 100, data["baseline"]["macro_f1"] * 100]
    a = ax.bar(x - .16, acc, .32, label="Accuracy", color=TEAL)
    b = ax.bar(x + .16, f1, .32, label="Macro F1 × 100", color="#6fa5bd")
    ax.set(xticks=x, xticklabels=names, ylim=(0, 111), ylabel="Score on 0–100 scale", title="Same held-out set, two classifiers")
    ax.legend(loc="upper center", frameon=False, ncol=2)
    ax.bar_label(a, fmt="%.2f", padding=3)
    ax.bar_label(b, fmt="%.2f", padding=3)
    ax.grid(axis="y", color="#e3eaed")
    ax.set_axisbelow(True)
    save(fig, "model_comparison.png")

    with (EVIDENCE / "http_timings.csv").open(encoding="utf-8") as file:
        timings = list(csv.DictReader(file))
    with (EVIDENCE / "nlu_predictions.csv").open(encoding="utf-8") as file:
        inference = list(csv.DictReader(file))
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    for ax, values, title in (
        (axes[0], [float(row["inference_ms"]) for row in inference], "Warm NLU"),
        (axes[1], [float(row["ms"]) for row in timings], "Local HTTP turns"),
    ):
        values = sorted(values)
        ax.step(values, np.arange(1, len(values) + 1) / len(values) * 100, where="post", color=TEAL, linewidth=2)
        ax.axhline(95, color="#a78754", linestyle="--", linewidth=1)
        ax.set(title=f"{title} (n={len(values)})", xlabel="Latency (ms)", ylim=(0, 103))
        ax.grid(color="#e3eaed")
    axes[0].set_ylabel("Cumulative share (%)")
    fig.tight_layout()
    save(fig, "latency_ecdf.png")

    cases = data["workflows"]["cases"]
    totals = Counter(row["group"] for row in cases)
    passing = Counter(row["group"] for row in cases if row["status"] == "PASS")
    names = sorted(totals)
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    bars = ax.barh(names, [passing[name] for name in names], color=TEAL)
    ax.set(xlim=(0, max(totals.values()) + 2), xlabel="Scenarios", title="Acceptance checks by capability")
    ax.bar_label(bars, labels=[f"{passing[name]}/{totals[name]}" for name in names], padding=4)
    ax.grid(axis="x", color="#e3eaed")
    ax.set_axisbelow(True)
    save(fig, "workflow_coverage.png")

    selected = {"Confirmed transfer reconciliation", "Duplicate confirmation and conflicting ID",
                "Competing transfers", "Fraud report ownership", "Rasa HTTP contract via stub"}
    workflow, score, baseline = data["workflows"], data["nlu"], data["baseline"]
    lines = [f"{case['status']}  {case['name']}" for case in cases if case["name"] in selected]
    lines += ["", f"Workflow checks {workflow['passed']}/{workflow['total']}.",
              f"Held-out intents {score['correct']}/{score['examples']} ({score['accuracy']:.2%}), macro F1 {score['macro_f1']:.4f}.",
              f"Baseline {baseline['accuracy']:.2%}, macro F1 {baseline['macro_f1']:.4f}.",
              f"Measured {data['http_latency']['count']} HTTP turns."]
    fig = plt.figure(figsize=(8.6, 3.7))
    panel = fig.add_axes((.02, .02, .96, .96), facecolor=NAVY)
    panel.set(xticks=[], yticks=[])
    for spine in panel.spines.values():
        spine.set_visible(False)
    panel.text(.045, .92, "Saved evaluator output", color="#b3dacf", weight="bold", fontsize=14, va="top")
    panel.text(.045, .80, "\n".join(lines), color="white", family="DejaVu Sans Mono", fontsize=11,
               linespacing=1.30, va="top")
    save(fig, "evaluator_output.png")

    for name in ("architecture", "transfer_states", "entity_relationships"):
        subprocess.run(["dot", "-Tpng", str(FIGURES / (name + ".dot")),
                        "-o", str(FIGURES / (name + ".png"))], check=True)
    print("Regenerated diagrams and result plots.")


if __name__ == "__main__":
    main()
