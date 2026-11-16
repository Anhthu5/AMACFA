"""Drive an actual HTTP audit and verify the report bytes returned by the server."""

import argparse
import json
from pathlib import Path
from uuid import uuid4

import httpx

from amacfa.config import Settings
from amacfa.models import AuditView, canonical_digest, sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--csv", type=Path, default=Path("data/invoices_mixed.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path(".amacfa/demo"))
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--decision", choices=["approve", "return"], default="approve")
    args = parser.parse_args()
    settings = Settings()
    analyst = {"Authorization": f"Bearer {settings.analyst_token.get_secret_value()}"}
    reviewer = {"Authorization": f"Bearer {settings.reviewer_token.get_secret_value()}"}
    audit_id = uuid4()
    endpoint = f"/audits/{audit_id}"

    with httpx.Client(base_url=args.base_url, timeout=180) as client:
        payload = args.csv.read_bytes()
        response = client.post(
            "/audits",
            content=payload,
            headers=analyst | {"Content-Type": "text/csv", "Idempotency-Key": str(audit_id)},
        )
        pending = AuditView.model_validate(response.raise_for_status().json())
        if pending.status != "awaiting_review" or pending.packet is None:
            raise RuntimeError(f"Expected pending review. Current state: {pending.status}")
        if pending.input_sha256 != sha256(payload) or pending.packet_sha256 != canonical_digest(
            pending.packet.model_dump(mode="json")
        ):
            raise RuntimeError("The uploaded CSV or evidence packet failed digest verification.")
        print(f"Audit {audit_id} · {pending.status}")
        print(f"Evidence SHA-256 {pending.packet_sha256}")
        for finding in pending.packet.findings:
            print(f"  {finding.id} {finding.rule:18} lines={finding.lines} {finding.control.id}")
        blocked = client.get(f"{endpoint}/report.md", headers=analyst)
        if blocked.status_code != 409:
            raise RuntimeError("The pre-approval report should have been blocked.")
        print("Report before review: HTTP 409")
        decision = args.decision
        if args.interactive:
            decision = input("Reviewer decision [approve/return]: ").strip().lower()
            if decision not in {"approve", "return"}:
                raise SystemExit("Use approve or return.")

        response = client.post(
            f"{endpoint}/review",
            json={"decision": decision, "note": "Reviewer verified the synthetic evidence packet."},
            headers=reviewer | {"X-Review-Packet-SHA256": pending.packet_sha256},
        )
        case = AuditView.model_validate(response.raise_for_status().json())
        args.output_dir.mkdir(parents=True, exist_ok=True)
        record_path = args.output_dir / f"audit-{audit_id}.json"
        record_path.write_text(
            json.dumps(case.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Case {case.status} · {record_path}")

        response = client.get(f"{endpoint}/report.md", headers=analyst)
        if decision == "return":
            if case.status != "returned" or response.status_code != 409:
                raise RuntimeError("Returning the audit must keep the report blocked.")
            return 0
        content = response.raise_for_status().content
        if (
            case.status != "completed"
            or case.report is None
            or case.report.sha256 != sha256(content)
        ):
            raise RuntimeError("The exported report failed digest verification.")
        report_path = args.output_dir / f"audit-{audit_id}.md"
        report_path.write_bytes(content)
        print(f"Report SHA-256 verified · {case.report.ranking_source} · {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
