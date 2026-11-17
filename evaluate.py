"""Reproduce the saved intent scores and loopback workflow evidence."""

from argparse import ArgumentParser
from datetime import datetime, timezone
from hashlib import sha256
import csv
import json
from math import ceil
from pathlib import Path
import platform
from statistics import mean, median
from time import perf_counter
import sqlite3

from banking.nlu import PortableNLU
from tests.scenarios import MODEL, DATE, run_cases
from tools.corpus_io import ROOT, splits


def metrics(gold, predicted, classes):
    indices = {label: i for i, label in enumerate(classes)}
    matrix = [[0] * len(classes) for _ in classes]
    for expected, result in zip(gold, predicted):
        matrix[indices[expected]][indices[result]] += 1
    rows = []
    for i, label in enumerate(classes):
        tp, support = matrix[i][i], sum(matrix[i])
        predicted_count = sum(row[i] for row in matrix)
        precision = tp / predicted_count if predicted_count else 0
        recall = tp / support if support else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        rows.append({"intent": label, "tp": tp, "fp": predicted_count - tp, "fn": support - tp,
                     "precision": precision, "recall": recall, "f1": f1, "support": support})
    correct = sum(row["tp"] for row in rows)
    return {"correct": correct, "examples": len(gold), "accuracy": correct / len(gold),
            "macro_f1": mean(row["f1"] for row in rows), "matrix": matrix, "by_intent": rows}


def latency(values):
    sorted_values = sorted(values)
    if not sorted_values:
        return {}
    return {"count": len(sorted_values), "mean_ms": mean(sorted_values), "p50_ms": median(sorted_values),
            "p95_ms": sorted_values[ceil(.95 * len(sorted_values)) - 1], "max_ms": sorted_values[-1]}


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "evidence")
    output = parser.parse_args().out
    output.mkdir(parents=True, exist_ok=True)
    training, heldout = splits()
    model = PortableNLU(MODEL)
    meta = json.loads((ROOT / "models" / "training_metadata.json").read_text(encoding="utf-8"))
    gold = [label for _, label in heldout]
    for text, _ in training[:20]:
        model.parse(text)
    predictions = []
    for text, label in heldout:
        start = perf_counter()
        result = model.parse(text)
        predictions.append({"text": text, "expected": label, "predicted": result.intent,
                            "confidence": round(result.confidence, 6), "margin": round(result.margin, 6),
                            "inference_ms": round((perf_counter() - start) * 1000, 4)})
    score = metrics(gold, [row["predicted"] for row in predictions], model.classes)
    baseline = metrics(gold, meta["baseline"], model.classes)
    checks = run_cases()
    turns = [{"scenario": row["name"], "group": row["group"], **turn}
             for row in checks for turn in row["timings"]]
    passed = sum(row["status"] == "PASS" for row in checks)
    report = {
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fixture_date": DATE.isoformat(), "python": platform.python_version(),
        "platform": platform.platform(), "sqlite": sqlite3.sqlite_version,
        "model": model.name, "model_sha256": sha256(MODEL.read_bytes()).hexdigest(),
        "training": {key: value for key, value in meta.items() if key != "baseline"},
        "nlu": score, "baseline": baseline, "classes": model.classes,
        "inference_latency": latency([row["inference_ms"] for row in predictions]),
        "http_latency": latency([row["ms"] for row in turns]),
        "workflows": {"passed": passed, "total": len(checks),
                      "cases": [{"name": row["name"], "group": row["group"], "status": row["status"],
                                 "observed": row["observed"]} for row in checks]},
    }
    write_json(output / "summary.json", report)
    write_json(output / "workflow_traces.json", checks)
    write_csv(output / "nlu_predictions.csv", predictions)
    write_csv(output / "http_timings.csv", turns)
    write_csv(output / "per_intent_metrics.csv", score["by_intent"])
    write_csv(output / "baseline_predictions.csv",
              [{"text": text, "expected": expected, "predicted": result}
               for (text, expected), result in zip(heldout, meta["baseline"])])
    for row in checks:
        print(f"{row['status']:4}  {row['name']}  |  {row['observed']}")
    print(f"\nWorkflow checks {passed}/{len(checks)}. Held-out intents {score['correct']}/{len(gold)} "
          f"({score['accuracy']:.2%}), macro F1 {score['macro_f1']:.4f}.")
    print(f"Baseline {baseline['accuracy']:.2%}, macro F1 {baseline['macro_f1']:.4f}.")
    print(f"Measured {len(turns)} HTTP turns. Evidence in {output}")
    if passed != len(checks):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
