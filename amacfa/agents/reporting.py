"""Render an approved Vietnamese report entirely from validated case data."""

from amacfa.models import AuditPacket, ExecutiveReport, Review, Severity, canonical_digest, sha256
from amacfa.tools.llm import Ranker
from amacfa.workflows.state import AuditState

METRIC_LABELS = {
    "amount": "Giá trị",
    "threshold": "Hạn mức",
    "currency": "Tiền tệ",
    "sum": "Tổng",
    "window_days": "Cửa sổ (ngày)",
    "vendor_count": "Số nhà cung cấp",
    "evidence_path": "Đường dẫn quan hệ",
}


def executive_reporting(state: AuditState, ranker: Ranker) -> dict:
    review = Review.model_validate(state["review"])
    packet = AuditPacket.model_validate(state["packet"])
    if (
        review.decision != "approve"
        or packet.audit_id != state["audit_id"]
        or review.packet_sha256 != state["packet_sha256"]
        or review.packet_sha256 != canonical_digest(packet.model_dump(mode="json"))
    ):
        raise ValueError("Publishing requires approval of this evidence packet.")
    ranking = ranker(packet.findings)
    by_id = {finding.id: finding for finding in packet.findings}
    high = sum(finding.severity == Severity.HIGH for finding in packet.findings)
    flagged = len({line for item in packet.findings for line in item.lines})
    summary = (
        f"Rà soát {len(packet.rows)} hóa đơn. Ghi nhận {len(packet.findings)} tín hiệu, "
        f"gồm {high} mức cao, liên quan đến {flagged} dòng CSV."
    )
    lines = [
        "# Báo cáo kiểm toán công nợ phải trả",
        "",
        summary,
        "",
        f"- Hồ sơ `{state['audit_id']}`",
        f"- Chính sách nội bộ `{packet.policy_version}`",
        f"- SHA-256 CSV `{packet.input_sha256}`",
        f"- SHA-256 gói bằng chứng đã duyệt `{review.packet_sha256}`",
        f"- Phê duyệt `{review.actor}` · `{review.reviewed_at.isoformat()}`",
        "",
        "Các tín hiệu cần được xác minh bằng hồ sơ gốc trước khi đưa ra kết luận nghiệp vụ.",
    ]
    if ranking.ids:
        lines += ["", "## Việc cần ưu tiên", ""]
        lines += [f"- **{key}** · {by_id[key].action}" for key in ranking.ids]
    if packet.findings:
        lines += ["", "## Bằng chứng và căn cứ chính sách"]
    for finding in packet.findings:
        references = ", ".join(map(str, finding.lines))
        level = "Cao" if finding.severity == Severity.HIGH else "Trung bình"
        lines += [
            "",
            f"### {finding.id} · {finding.control.title}",
            "",
            f"- Quy tắc `{finding.rule}` · Mức {level} · Dòng CSV **{references}**",
            f"- Điều khoản `{finding.control.id}@{finding.control.version}` · {finding.control.clause}",
            f"- Xác minh · {finding.action}",
        ]
        if finding.metrics:
            lines += [
                "- Chỉ số · "
                + " · ".join(
                    f"{METRIC_LABELS[key]} `{value}`" for key, value in finding.metrics.items()
                )
            ]
        if finding.related_controls:
            references = ", ".join(
                f"`{citation.id}@{citation.version}`" for citation in finding.related_controls
            )
            lines += [f"- Điều khoản tham khảo · {references}"]
    markdown = "\n".join(lines) + "\n"
    report = ExecutiveReport(
        summary=summary,
        priority_finding_ids=ranking.ids,
        ranking_source=ranking.source,
        ranking_model=ranking.model,
        markdown=markdown,
        sha256=sha256(markdown.encode("utf-8")),
    )
    return {"report": report.model_dump(mode="json")}
