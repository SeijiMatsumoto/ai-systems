"""Deterministic log replay, grouping, and incident candidate selection.

This module does not classify candidates or launch the investigator. The caller
owns replay pacing; yielding one event at a time makes the same logic usable by
the offline CLI and a later streaming API.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from backend.incident_investigation.telemetry import LogEvent, TelemetryStore

REPLAY_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "v2"
GROUP_WINDOW = timedelta(minutes=5)
MIN_ERROR_REQUESTS = 3
MAX_REPLAY_LOGS = 2_000


class ReplayStep(BaseModel):
    sequence: int
    log: LogEvent
    signature: str
    group_id: str
    group_count: int
    cluster_id: str | None
    cluster_services: list[str]
    distinct_error_requests: int
    decision: Literal["routine", "below_threshold", "candidate", "duplicate_candidate"]
    reason: str


@dataclass
class SignatureGroup:
    id: str
    service: str
    level: str
    signature: str
    last_seen: datetime
    count: int = 0


@dataclass
class CorrelationCluster:
    id: str
    group_ids: set[str] = field(default_factory=set)
    records: list[LogEvent] = field(default_factory=list)
    candidate_emitted: bool = False


def normalize_message(message: str) -> str:
    """Mask changing identifiers while retaining the service-specific error shape."""
    value = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<id>", message.lower())
    value = re.sub(r"(?<!http )\b\d+\b", "<n>", value)
    return " ".join(value.split())


def _request_key(log: LogEvent) -> str:
    request_id = log.attributes.get("request_id")
    if isinstance(request_id, str) and request_id:
        return request_id
    return log.trace_id or log.evidence_id


def replay_logs(store: TelemetryStore | None = None) -> Iterator[ReplayStep]:
    """Replay each record exactly once; emit a candidate once per correlated cluster."""
    store = store or TelemetryStore(REPLAY_FIXTURE_DIR)
    logs = sorted(store.logs, key=lambda item: (item.observed_at, item.evidence_id))
    if len(logs) > MAX_REPLAY_LOGS:
        raise ValueError("replay fixture exceeds the log limit")

    groups: dict[tuple[str, str, str], SignatureGroup] = {}
    clusters: dict[str, CorrelationCluster] = {}
    group_cluster: dict[str, str] = {}
    request_clusters: dict[str, set[str]] = {}
    trace_clusters: dict[str, set[str]] = {}
    aliases: dict[str, str] = {}

    def canonical(cluster_id: str) -> str:
        while cluster_id in aliases:
            cluster_id = aliases[cluster_id]
        return cluster_id

    for sequence, log in enumerate(logs, start=1):
        signature = normalize_message(log.message)
        key = (log.service, log.level, signature)
        group = groups.get(key)
        if group is None or log.observed_at - group.last_seen > GROUP_WINDOW:
            group = SignatureGroup(
                id=f"group-{sequence:04d}",
                service=log.service,
                level=log.level,
                signature=signature,
                last_seen=log.observed_at,
            )
            groups[key] = group
        group.last_seen = log.observed_at
        group.count += 1

        if log.level not in {"WARN", "ERROR"}:
            yield ReplayStep(
                sequence=sequence,
                log=log,
                signature=signature,
                group_id=group.id,
                group_count=group.count,
                cluster_id=None,
                cluster_services=[],
                distinct_error_requests=0,
                decision="routine",
                reason="Informational log; grouped for display, not incident candidacy.",
            )
            continue

        related_services = set(store.manifest.related_services[log.service])
        possible = set()
        if group.id in group_cluster:
            possible.add(canonical(group_cluster[group.id]))
        request_id = log.attributes.get("request_id")
        if isinstance(request_id, str) and request_id:
            possible.update(
                canonical(item) for item in request_clusters.get(request_id, set())
            )
        if log.trace_id:
            possible.update(
                canonical(item) for item in trace_clusters.get(log.trace_id, set())
            )
        matching = sorted(
            cluster_id
            for cluster_id in possible
            if any(
                record.service in related_services
                and log.observed_at - record.observed_at <= GROUP_WINDOW
                for record in clusters[cluster_id].records
            )
        )
        cluster_id = matching[0] if matching else f"cluster-{sequence:04d}"
        cluster = clusters.setdefault(cluster_id, CorrelationCluster(id=cluster_id))
        for other_id in matching[1:]:
            other = clusters.pop(other_id)
            cluster.group_ids.update(other.group_ids)
            cluster.records.extend(other.records)
            cluster.candidate_emitted |= other.candidate_emitted
            aliases[other_id] = cluster_id
        cluster.group_ids.add(group.id)
        cluster.records.append(log)
        group_cluster[group.id] = cluster_id
        if isinstance(request_id, str) and request_id:
            request_clusters.setdefault(request_id, set()).add(cluster_id)
        if log.trace_id:
            trace_clusters.setdefault(log.trace_id, set()).add(cluster_id)

        window_start = log.observed_at - GROUP_WINDOW
        distinct_errors = {
            _request_key(record)
            for record in cluster.records
            if record.level == "ERROR"
            and window_start <= record.observed_at <= log.observed_at
        }
        if len(distinct_errors) < MIN_ERROR_REQUESTS:
            decision = "below_threshold"
            reason = (
                f"{len(distinct_errors)} distinct error requests in five minutes; "
                f"requires {MIN_ERROR_REQUESTS}."
            )
        elif cluster.candidate_emitted:
            decision = "duplicate_candidate"
            reason = "Candidate already emitted for this correlated cluster."
        else:
            decision = "candidate"
            reason = f"{len(distinct_errors)} distinct error requests in five minutes."
            cluster.candidate_emitted = True
        yield ReplayStep(
            sequence=sequence,
            log=log,
            signature=signature,
            group_id=group.id,
            group_count=group.count,
            cluster_id=cluster_id,
            cluster_services=sorted({record.service for record in cluster.records}),
            distinct_error_requests=len(distinct_errors),
            decision=decision,
            reason=reason,
        )
