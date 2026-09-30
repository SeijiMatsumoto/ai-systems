"""Resolve cited fixture records and check report boundaries deterministically."""

from __future__ import annotations

import json
from datetime import datetime

from backend.incident_investigation.agent import InvestigationDraft
from backend.incident_investigation.contracts import (
    IncidentClaim,
    IncidentReport,
    TelemetryEvidence,
    VerificationIssue,
    VerificationResult,
)
from backend.incident_investigation.telemetry import (
    Alert,
    ChangeEvent,
    InvestigationScope,
    LogEvent,
    MetricPoint,
    TelemetryStore,
    TraceSpan,
)

Record = Alert | LogEvent | MetricPoint | TraceSpan | ChangeEvent


def _observed_at(record: Record) -> datetime:
    return record.started_at if isinstance(record, TraceSpan) else record.observed_at


def _evidence(record: Record) -> TelemetryEvidence:
    if isinstance(record, Alert):
        source, excerpt = "alert", f"{record.title}: {record.description}"
    elif isinstance(record, LogEvent):
        source, excerpt = "log", record.message
    elif isinstance(record, MetricPoint):
        source, excerpt = "metric", f"{record.metric}={record.value:g} {record.unit}"
    elif isinstance(record, TraceSpan):
        source, excerpt = "trace", f"{record.operation} ({record.status})"
    else:
        source = "change"
        excerpt = f"{record.description}: {json.dumps(record.details, sort_keys=True)}"
    return TelemetryEvidence(
        evidence_id=record.evidence_id,
        source=source,
        service=record.service,
        locator=record.locator,
        observed_at=_observed_at(record),
        excerpt=excerpt,
    )


def verify_report(
    draft: InvestigationDraft,
    *,
    store: TelemetryStore,
    scope: InvestigationScope,
    surfaced_evidence_ids: set[str],
) -> tuple[IncidentReport | None, VerificationResult]:
    """Verify citation provenance and structure; human review judges interpretation."""
    records: dict[str, Record] = {
        record.evidence_id: record
        for record in [
            *([store.manifest.alert] if store.manifest.alert is not None else []),
            *store.logs,
            *store.metrics,
            *store.spans,
            *store.changes,
        ]
    }
    issues: list[VerificationIssue] = []
    if not draft.observations:
        issues.append(VerificationIssue(code="empty_report", path="observations"))

    used_ids: set[str] = set()
    for group_name, claims, allowed_kinds in (
        ("observations", draft.observations, {"fact", "correlation"}),
        ("candidate_causes", draft.candidate_causes, {"hypothesis"}),
    ):
        for index, claim in enumerate(claims):
            path = f"{group_name}[{index}]"
            if claim.kind not in allowed_kinds:
                issues.append(
                    VerificationIssue(code="invalid_kind", path=f"{path}.kind")
                )
            for evidence_id in claim.evidence_ids:
                record = records.get(evidence_id)
                if record is None:
                    issues.append(
                        VerificationIssue(
                            code="unknown_evidence",
                            path=f"{path}.evidence_ids",
                            evidence_id=evidence_id,
                        )
                    )
                    continue
                if evidence_id not in surfaced_evidence_ids:
                    issues.append(
                        VerificationIssue(
                            code="not_surfaced",
                            path=f"{path}.evidence_ids",
                            evidence_id=evidence_id,
                        )
                    )
                    continue
                if (
                    record.service not in scope.allowed_services
                    or not scope.start <= _observed_at(record) <= scope.end
                ):
                    issues.append(
                        VerificationIssue(
                            code="outside_scope",
                            path=f"{path}.evidence_ids",
                            evidence_id=evidence_id,
                        )
                    )
                    continue
                used_ids.add(evidence_id)

    if issues:
        return None, VerificationResult(passed=False, issues=issues)

    def report_claim(claim) -> IncidentClaim:
        return IncidentClaim(
            statement=claim.statement,
            kind=claim.kind,
            evidence_ids=list(dict.fromkeys(claim.evidence_ids)),
        )

    timeline = sorted(
        (report_claim(claim) for claim in draft.observations),
        key=lambda claim: min(
            _observed_at(records[evidence_id]) for evidence_id in claim.evidence_ids
        ),
    )
    gaps = [
        gap
        for gap in store.manifest.coverage_gaps
        if gap.service in scope.allowed_services
        and gap.start < scope.end
        and gap.end > scope.start
    ]
    unknowns = list(draft.unknowns)
    for gap in gaps:
        disclosure = (
            f"{gap.source} coverage gap for {gap.service}: "
            f"{gap.start.isoformat()} to {gap.end.isoformat()} ({gap.reason})"
        )
        if disclosure not in unknowns:
            unknowns.append(disclosure)
    evidence = sorted(
        (_evidence(records[evidence_id]) for evidence_id in used_ids),
        key=lambda item: (item.observed_at, item.evidence_id),
    )
    report = IncidentReport(
        timeline=timeline,
        likely_causes=[report_claim(claim) for claim in draft.candidate_causes],
        unknowns=unknowns,
        next_checks=draft.next_checks,
        coverage_gaps=gaps,
        evidence=evidence,
    )
    return report, VerificationResult(passed=True, issues=[])
