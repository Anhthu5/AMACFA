"""Bind each signal to its authoritative policy control and supporting context."""

from amacfa.models import AuditPacket, Finding, Policy, Signal, canonical_digest
from amacfa.tools.policy import RelatedSearch, cite
from amacfa.workflows.state import AuditState


def compliance_agent(state: AuditState, policy: Policy, search: RelatedSearch) -> dict:
    controls = {control.rule: control for control in policy.controls}
    related = (
        {rule: search(control) for rule, control in controls.items()} if state["signals"] else {}
    )
    findings = []
    for index, signal in enumerate(map(Signal.model_validate, state["signals"]), start=1):
        control = controls[signal.rule]
        findings.append(
            Finding(
                **signal.model_dump(),
                id=f"F-{index:04d}",
                severity=control.severity,
                control=cite(policy, control),
                related_controls=related[signal.rule],
                action=control.action,
            )
        )
    # The review binds to the full canonical packet, including its evidence and clause text.
    packet = AuditPacket.model_validate(
        {
            key: state[key]
            for key in (
                "audit_id",
                "input_sha256",
                "policy_sha256",
                "policy_version",
                "graph_backend",
                "vector_backend",
                "rows",
            )
        }
        | {"findings": findings}
    ).model_dump(mode="json")
    return {"packet": packet, "packet_sha256": canonical_digest(packet)}
