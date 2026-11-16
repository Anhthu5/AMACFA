"""Reproducible accounts-payable tests with no LLM dependencies."""

from collections import defaultdict
from decimal import Decimal

from amacfa.models import Evidence, Policy, Rule, Signal


def invoice_key(row: Evidence) -> tuple[str, str]:
    invoice = row.invoice
    return invoice.vendor_id, invoice.invoice_number


def detect_anomalies(rows: list[Evidence], policy: Policy) -> list[Signal]:
    by_invoice: dict[tuple[str, str], list[int]] = defaultdict(list)
    for row in rows:
        by_invoice[invoice_key(row)].append(row.line)
    findings = [
        Signal(rule=Rule.DUPLICATE, lines=sorted(lines))
        for lines in by_invoice.values()
        if len(lines) > 1
    ]

    candidates: dict[tuple[str, str, str], list[Evidence]] = defaultdict(list)
    for row in rows:
        invoice = row.invoice
        threshold = policy.approval_thresholds[invoice.currency]
        if invoice.approved_by == invoice.requested_by:
            findings.append(Signal(rule=Rule.SELF_APPROVAL, lines=[row.line]))
        if invoice.amount >= threshold and invoice.approved_by is None:
            findings.append(
                Signal(
                    rule=Rule.MISSING_APPROVAL,
                    lines=[row.line],
                    metrics={
                        "amount": str(invoice.amount),
                        "threshold": str(threshold),
                        "currency": invoice.currency,
                    },
                )
            )
        if invoice.amount < threshold and len(by_invoice[invoice_key(row)]) == 1:
            candidates[invoice.vendor_id, invoice.requested_by, invoice.currency].append(row)

    for (_, _, currency), group in candidates.items():
        findings.extend(
            _split_signals(
                group, policy.approval_thresholds[currency], policy.split_window_days, currency
            )
        )
    return findings


def _split_signals(
    rows: list[Evidence], threshold: Decimal, days: int, currency: str
) -> list[Signal]:
    """Emit the first crossing in each disjoint window, ordered by date and line."""
    rows = sorted(rows, key=lambda row: (row.invoice.issued_on, row.line))
    findings: list[Signal] = []
    left = 0
    total = Decimal(0)
    for right, row in enumerate(rows):
        total += row.invoice.amount
        while (row.invoice.issued_on - rows[left].invoice.issued_on).days >= days:
            total -= rows[left].invoice.amount
            left += 1
        if total >= threshold:
            findings.append(
                Signal(
                    rule=Rule.SPLIT,
                    lines=sorted(item.line for item in rows[left : right + 1]),
                    metrics={
                        "sum": str(total),
                        "threshold": str(threshold),
                        "currency": currency,
                        "window_days": days,
                    },
                )
            )
            left = right + 1
            total = Decimal(0)
    return findings
