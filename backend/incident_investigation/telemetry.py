"""Versioned synthetic incident records and scoped, read-only queries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "v1"
MAX_WINDOW = timedelta(hours=2)
MAX_LOG_RESULTS = 50
MAX_TRACE_SPANS = 30
MAX_CHANGE_RESULTS = 20
MAX_METRIC_POINTS = 121


class Alert(BaseModel):
    evidence_id: str
    observed_at: datetime
    service: str
    title: str
    description: str
    locator: str


class CoverageGap(BaseModel):
    source: Literal["log", "metric", "trace", "change"]
    service: str
    start: datetime
    end: datetime
    reason: str


class Manifest(BaseModel):
    fixture_id: str
    version: int
    window_start: datetime
    window_end: datetime
    services: list[str]
    related_services: dict[str, list[str]]
    alert: Alert | None = None
    coverage_gaps: list[CoverageGap]


class LogEvent(BaseModel):
    evidence_id: str
    observed_at: datetime
    service: str
    level: Literal["DEBUG", "INFO", "WARN", "ERROR"]
    message: str
    trace_id: str | None = None
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)
    locator: str


class MetricPoint(BaseModel):
    evidence_id: str
    observed_at: datetime
    service: str
    metric: str
    value: float
    unit: str
    locator: str


class TraceSpan(BaseModel):
    evidence_id: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    service: str
    operation: str
    started_at: datetime
    ended_at: datetime
    status: Literal["OK", "ERROR"]
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)
    locator: str


class ChangeEvent(BaseModel):
    evidence_id: str
    observed_at: datetime
    service: str
    kind: Literal["deployment", "configuration"]
    description: str
    details: dict[str, str]
    locator: str


T = TypeVar("T")


@dataclass(frozen=True)
class QueryResult(Generic[T]):
    records: list[T]
    truncated: bool
    coverage_gaps: list[CoverageGap]


@dataclass(frozen=True)
class InvestigationScope:
    alert_id: str
    allowed_services: frozenset[str]
    start: datetime
    end: datetime


def _utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _load_jsonl(path: Path, model: type[T]) -> list[T]:
    with path.open(encoding="utf-8") as stream:
        return [
            model.model_validate(json.loads(line)) for line in stream if line.strip()
        ]


class TelemetryStore:
    def __init__(self, fixture_dir: Path = FIXTURE_DIR) -> None:
        self.fixture_dir = fixture_dir
        self.manifest = Manifest.model_validate_json(
            (fixture_dir / "manifest.json").read_text(encoding="utf-8")
        )
        self.logs = _load_jsonl(fixture_dir / "logs.jsonl", LogEvent)
        self.metrics = _load_jsonl(fixture_dir / "metrics.jsonl", MetricPoint)
        self.spans = _load_jsonl(fixture_dir / "traces.jsonl", TraceSpan)
        self.changes = _load_jsonl(fixture_dir / "changes.jsonl", ChangeEvent)
        self._validate_fixture()

    def _validate_fixture(self) -> None:
        manifest = self.manifest
        start = _utc(manifest.window_start, "fixture start")
        end = _utc(manifest.window_end, "fixture end")
        if start >= end or end - start > MAX_WINDOW:
            raise ValueError("fixture window must be positive and at most two hours")
        services = set(manifest.services)
        if not services or len(services) != len(manifest.services):
            raise ValueError("fixture services must be unique and nonempty")
        if set(manifest.related_services) != services:
            raise ValueError("service topology must define every service")
        for service, related in manifest.related_services.items():
            if service not in related or not set(related) <= services:
                raise ValueError("service topology contains an invalid relationship")
        fixture_prefix = f"fixtures/{self.fixture_dir.name}"
        ids: set[str] = set()
        if manifest.alert is not None:
            if manifest.alert.service not in services:
                raise ValueError("alert service is unknown")
            if not start <= _utc(manifest.alert.observed_at, "alert timestamp") <= end:
                raise ValueError("alert is outside fixture window")
            if (
                manifest.alert.locator
                != f"{fixture_prefix}/manifest.json#{manifest.alert.evidence_id}"
            ):
                raise ValueError("alert locator does not match its evidence ID")
            ids.add(manifest.alert.evidence_id)
        groups = [
            ("logs", self.logs),
            ("metrics", self.metrics),
            ("traces", self.spans),
            ("changes", self.changes),
        ]
        for source, records in groups:
            for record in records:
                if record.evidence_id in ids:
                    raise ValueError(f"duplicate evidence ID: {record.evidence_id}")
                ids.add(record.evidence_id)
                if record.service not in services:
                    raise ValueError(f"unknown service: {record.service}")
                at = (
                    record.started_at
                    if isinstance(record, TraceSpan)
                    else record.observed_at
                )
                if not start <= _utc(at, "record timestamp") <= end:
                    raise ValueError(
                        f"record outside fixture window: {record.evidence_id}"
                    )
                if (
                    record.locator
                    != f"{fixture_prefix}/{source}.jsonl#{record.evidence_id}"
                ):
                    raise ValueError(
                        f"locator does not match evidence ID: {record.evidence_id}"
                    )

        trace_spans = {(span.trace_id, span.span_id) for span in self.spans}
        if len(trace_spans) != len(self.spans):
            raise ValueError("duplicate trace span ID")
        for span in self.spans:
            if _utc(span.ended_at, "span end") < _utc(span.started_at, "span start"):
                raise ValueError(f"negative trace duration: {span.evidence_id}")
            if (
                span.parent_span_id
                and (span.trace_id, span.parent_span_id) not in trace_spans
            ):
                raise ValueError(f"missing parent span: {span.evidence_id}")

        for gap in manifest.coverage_gaps:
            if (
                gap.service not in services
                or not start
                <= _utc(gap.start, "gap start")
                < _utc(gap.end, "gap end")
                <= end
            ):
                raise ValueError("invalid coverage gap")

    def scope_for_alert(
        self, alert_id: str, start: datetime, end: datetime
    ) -> InvestigationScope:
        manifest = self.manifest
        if manifest.alert is None or alert_id != manifest.alert.evidence_id:
            raise ValueError("unknown alert ID")
        start_utc = _utc(start, "query start")
        end_utc = _utc(end, "query end")
        if start_utc >= end_utc or end_utc - start_utc > MAX_WINDOW:
            raise ValueError("query window must be positive and at most two hours")
        if start_utc < _utc(manifest.window_start, "fixture start") or end_utc > _utc(
            manifest.window_end, "fixture end"
        ):
            raise ValueError("query window exceeds fixture window")
        return InvestigationScope(
            alert_id=alert_id,
            allowed_services=frozenset(
                manifest.related_services[manifest.alert.service]
            ),
            start=start_utc,
            end=end_utc,
        )

    def _window(
        self, scope: InvestigationScope, service: str, start: datetime, end: datetime
    ) -> tuple[datetime, datetime]:
        if service not in scope.allowed_services:
            raise ValueError("service is outside investigation scope")
        start_utc = _utc(start, "query start")
        end_utc = _utc(end, "query end")
        if start_utc >= end_utc or start_utc < scope.start or end_utc > scope.end:
            raise ValueError("query window is outside investigation scope")
        return start_utc, end_utc

    def _gaps(
        self, source: str, service: str, start: datetime, end: datetime
    ) -> list[CoverageGap]:
        return [
            gap
            for gap in self.manifest.coverage_gaps
            if gap.source == source
            and gap.service == service
            and _utc(gap.start, "gap start") < end
            and _utc(gap.end, "gap end") > start
        ]

    def search_logs(
        self,
        scope: InvestigationScope,
        service: str,
        start: datetime,
        end: datetime,
        *,
        level: str | None = None,
        trace_id: str | None = None,
        limit: int = 20,
    ) -> QueryResult[LogEvent]:
        start, end = self._window(scope, service, start, end)
        if level is not None and level not in {"DEBUG", "INFO", "WARN", "ERROR"}:
            raise ValueError("unknown log level")
        if not 1 <= limit <= MAX_LOG_RESULTS:
            raise ValueError("log limit is outside allowed range")
        matches = [
            record
            for record in self.logs
            if record.service == service
            and start <= record.observed_at <= end
            and (level is None or record.level == level)
            and (trace_id is None or record.trace_id == trace_id)
        ]
        matches.sort(key=lambda record: (record.observed_at, record.evidence_id))
        return QueryResult(
            matches[:limit],
            len(matches) > limit,
            self._gaps("log", service, start, end),
        )

    def get_metric_series(
        self,
        scope: InvestigationScope,
        service: str,
        metric: str,
        start: datetime,
        end: datetime,
    ) -> QueryResult[MetricPoint]:
        start, end = self._window(scope, service, start, end)
        available = {point.metric for point in self.metrics if point.service == service}
        if metric not in available:
            raise ValueError("unknown metric for service")
        matches = [
            point
            for point in self.metrics
            if point.service == service
            and point.metric == metric
            and start <= point.observed_at <= end
        ]
        matches.sort(key=lambda point: (point.observed_at, point.evidence_id))
        return QueryResult(
            matches[:MAX_METRIC_POINTS],
            len(matches) > MAX_METRIC_POINTS,
            self._gaps("metric", service, start, end),
        )

    def inspect_trace(
        self, scope: InvestigationScope, trace_id: str
    ) -> QueryResult[TraceSpan]:
        matches = [
            span
            for span in self.spans
            if span.trace_id == trace_id
            and span.service in scope.allowed_services
            and scope.start <= span.started_at <= scope.end
        ]
        if not matches:
            raise ValueError("trace is unknown or outside investigation scope")
        matches.sort(key=lambda span: (span.started_at, span.evidence_id))
        gaps = [
            gap
            for gap in self.manifest.coverage_gaps
            if gap.source == "trace"
            and gap.service in scope.allowed_services
            and any(
                _utc(gap.start, "gap start")
                <= span.started_at
                < _utc(gap.end, "gap end")
                for span in matches
            )
        ]
        return QueryResult(
            matches[:MAX_TRACE_SPANS], len(matches) > MAX_TRACE_SPANS, gaps
        )

    def list_changes(
        self,
        scope: InvestigationScope,
        service: str,
        start: datetime,
        end: datetime,
    ) -> QueryResult[ChangeEvent]:
        start, end = self._window(scope, service, start, end)
        matches = [
            change
            for change in self.changes
            if change.service == service and start <= change.observed_at <= end
        ]
        matches.sort(key=lambda change: (change.observed_at, change.evidence_id))
        return QueryResult(
            matches[:MAX_CHANGE_RESULTS],
            len(matches) > MAX_CHANGE_RESULTS,
            self._gaps("change", service, start, end),
        )
