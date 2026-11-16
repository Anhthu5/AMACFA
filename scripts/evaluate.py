"""Evaluate exact rule, source-line set and control attribution on labeled fixtures."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient

from amacfa.config import DEMO_ANALYST, Settings
from main import create_app

DATA = Path(__file__).resolve().parents[1] / "data"


def key(result: dict) -> tuple:
    return result["rule"], tuple(result["lines"]), result["control"]


def main() -> int:
    expected = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
    tp = fp = fn = 0
    with TemporaryDirectory() as state:
        app = create_app(
            Settings(
                _env_file=None,
                state_dir=Path(state),
                demo_mode=True,
                analyst_token=DEMO_ANALYST,
                reviewer_token="eval-only-reviewer",
                graph_backend="local",
                vector_backend="local",
                llm_backend="offline",
            )
        )
        with TestClient(app) as client:
            for fixture, labels in expected.items():
                response = client.post(
                    "/audits",
                    content=(DATA / fixture).read_bytes(),
                    headers={
                        "Authorization": f"Bearer {DEMO_ANALYST}",
                        "Content-Type": "text/csv",
                        "Idempotency-Key": str(uuid4()),
                    },
                )
                findings = response.raise_for_status().json()["packet"]["findings"]
                predicted = {
                    key(finding | {"control": finding["control"]["id"]}) for finding in findings
                }
                reference = {key(label) for label in labels}
                tp += len(predicted & reference)
                fp += len(predicted - reference) + len(findings) - len(predicted)
                fn += len(reference - predicted)
                print(f"{fixture:20} expected={len(reference)} predicted={len(findings)}")
                for extra in sorted(predicted - reference):
                    print(f"  unexpected {extra}")
                for missing in sorted(reference - predicted):
                    print(f"  missing    {missing}")

    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    print(f"TP={tp} FP={fp} FN={fn} precision={precision:.3f} recall={recall:.3f} F1={f1:.3f}")
    return int(bool(fp or fn))


if __name__ == "__main__":
    raise SystemExit(main())
