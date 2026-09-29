"""Regenerate the checked-in v1 incident fixture with deterministic records."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


OUT = Path(__file__).parent / "v1"
BASE = datetime(2026, 4, 14, 14, 0, tzinfo=timezone.utc)
SERVICES = ["gateway", "storefront", "checkout", "payments", "inventory", "email-worker"]
REQUEST_PATH = ["gateway", "storefront", "checkout", "payments", "inventory"]


def at(minute: int, second: int = 0) -> str:
    return (BASE + timedelta(minutes=minute, seconds=second)).isoformat().replace("+00:00", "Z")


def write_jsonl(name: str, records: list[dict]) -> None:
    path = OUT / name
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def add_record(records: list[dict], source: str, record: dict) -> None:
    evidence_id = f"{source}-{len(records) + 1:04d}"
    record["evidence_id"] = evidence_id
    record["locator"] = f"fixtures/v1/{source}.jsonl#{evidence_id}"
    records.append(record)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "fixture_id": "checkout-payments-pool-2026-04-14",
        "version": 1,
        "window_start": at(0),
        "window_end": at(60),
        "services": SERVICES,
        "related_services": {
            **{service: REQUEST_PATH for service in REQUEST_PATH},
            "email-worker": ["email-worker"],
        },
        "alert": {
            "evidence_id": "alert-0001",
            "observed_at": at(19),
            "service": "checkout",
            "title": "Checkout 5xx rate above 5%",
            "description": "Checkout 5xx rate exceeded 5% for three consecutive minutes.",
            "locator": "fixtures/v1/manifest.json#alert-0001",
        },
        "coverage_gaps": [
            {
                "source": "trace",
                "service": "payments",
                "start": at(26),
                "end": at(32),
                "reason": "Payments spans were dropped by the synthetic 10% sampler during peak load; logs and metrics continue.",
            }
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    changes: list[dict] = []
    add_record(changes, "changes", {
        "observed_at": at(11), "service": "storefront", "kind": "deployment",
        "description": "Storefront release 2.18.0 completed",
        "details": {"version_before": "2.17.4", "version_after": "2.18.0", "change": "product-card copy and static assets"},
    })
    add_record(changes, "changes", {
        "observed_at": at(13), "service": "payments", "kind": "configuration",
        "description": "Payments database pool configuration applied",
        "details": {"db_pool_max_before": "40", "db_pool_max_after": "4", "change_ticket": "PAY-482"},
    })
    add_record(changes, "changes", {
        "observed_at": at(42), "service": "payments", "kind": "configuration",
        "description": "Payments database pool limit restored",
        "details": {"db_pool_max_before": "4", "db_pool_max_after": "40", "change_ticket": "PAY-482"},
    })
    write_jsonl("changes.jsonl", changes)

    metrics: list[dict] = []
    for minute in range(61):
        stressed = 15 <= minute < 42
        checkout_affected = 17 <= minute < 42
        severity = (
            0.45 if 15 <= minute < 19 else
            1.0 if 19 <= minute < 39 else
            0.6 if 39 <= minute < 42 else 0.0
        )
        for service in SERVICES:
            values = {
                "gateway": (180 + minute % 12, round(0.002 + (0.06 * severity if checkout_affected else 0), 3), 115 + minute % 14 + (1100 * severity if checkout_affected else 0)),
                "storefront": (170 + minute % 11, 0.001, 190 if minute in {11, 12} else 90 + minute % 11),
                "checkout": (72 + minute % 7, round(0.003 + (0.14 * severity if checkout_affected else 0), 3), 210 + minute % 21 + (4500 * severity if checkout_affected else 0)),
                "payments": (69 + minute % 8, round(0.002 + (0.18 * severity if stressed else 0), 3), 130 + minute % 17 + (4100 * severity if stressed else 0)),
                "inventory": (76 + minute % 6, 0.001, 170 if minute == 36 else 105 + minute % 9),
                "email-worker": (24 + minute % 4, 0.001, 80 + minute % 6),
            }
            rate, errors, p95 = values[service]
            for metric, value, unit in [
                ("request_rate_rps", rate, "requests/s"),
                ("error_rate", errors, "fraction"),
                ("p95_latency_ms", p95, "ms"),
            ]:
                add_record(metrics, "metrics", {
                    "observed_at": at(minute), "service": service,
                    "metric": metric, "value": value, "unit": unit,
                })
        for metric, value, unit in [
            ("db_pool_max", 4 if 13 <= minute < 42 else 40, "connections"),
            ("db_pool_active", 4 if stressed else 12 + minute % 4, "connections"),
            ("db_connection_wait_ms", round(8 + minute % 5 + (2600 * severity if stressed else 0)), "ms"),
        ]:
            add_record(metrics, "metrics", {
                "observed_at": at(minute), "service": "payments",
                "metric": metric, "value": value, "unit": unit,
            })
    write_jsonl("metrics.jsonl", metrics)

    trace_minutes = sorted(set(range(0, 60, 2)) | {15, 19, 23, 27, 31, 35, 39})
    trace_by_minute = {minute: f"trace-{minute:04d}" for minute in trace_minutes}
    spans: list[dict] = []
    for minute in trace_minutes:
        affected = 17 <= minute < 42
        trace_id = trace_by_minute[minute]
        span_specs = [
            ("gateway", "POST /checkout", "root", None, 0, 4700 if affected else 350),
            ("storefront", "forward checkout", "front", "root", 10, 4650 if affected else 330),
            ("checkout", "create order", "checkout", "front", 20, 4550 if affected else 300),
            ("inventory", "reserve items", "inventory", "checkout", 40, 95),
        ]
        if not 26 <= minute < 32:
            span_specs.append(("payments", "authorize payment", "payments", "checkout", 130, 4200 if affected else 125))
        for service, operation, span_id, parent, offset_ms, duration_ms in span_specs:
            started = BASE + timedelta(minutes=minute, milliseconds=offset_ms)
            ended = started + timedelta(milliseconds=duration_ms)
            add_record(spans, "traces", {
                "trace_id": trace_id, "span_id": span_id, "parent_span_id": parent,
                "service": service, "operation": operation,
                "started_at": started.isoformat().replace("+00:00", "Z"),
                "ended_at": ended.isoformat().replace("+00:00", "Z"),
                "status": "ERROR" if affected and service in {"gateway", "checkout", "payments"} else "OK",
                "attributes": {"http.route": "/checkout", "sampled": True},
            })
    write_jsonl("traces.jsonl", spans)

    logs: list[dict] = []
    messages = {
        "gateway": "Checkout request routed",
        "storefront": "Checkout page request forwarded",
        "checkout": "Order workflow started",
        "payments": "Payment authorization completed",
        "inventory": "Inventory reservation completed",
        "email-worker": "Receipt queue polled",
    }
    for minute in range(60):
        trace_id = trace_by_minute.get(minute)
        for index, service in enumerate(SERVICES):
            add_record(logs, "logs", {
                "observed_at": at(minute, index + 1), "service": service,
                "level": "INFO", "message": messages[service],
                "trace_id": None if service == "email-worker" else trace_id,
                "attributes": {
                    "request_id": f"receipt-{minute:04d}" if service == "email-worker" else f"req-{minute:04d}",
                    "instance": f"{service}-{1 + minute % 3}",
                },
            })
        if 15 <= minute < 42:
            add_record(logs, "logs", {
                "observed_at": at(minute, 12), "service": "payments", "level": "WARN",
                "message": "Database connection acquisition exceeded 2 seconds",
                "trace_id": trace_id,
                "attributes": {"request_id": f"req-{minute:04d}", "pool_active": 4, "pool_max": 4},
            })
        if 17 <= minute < 42:
            for service, message in [
                ("checkout", "Payment authorization timed out; order failed"),
                ("gateway", "Checkout upstream returned HTTP 503"),
            ]:
                add_record(logs, "logs", {
                    "observed_at": at(minute, 18 if service == "checkout" else 20),
                    "service": service, "level": "ERROR", "message": message,
                    "trace_id": trace_id,
                    "attributes": {"request_id": f"req-{minute:04d}", "http.status_code": 503},
                })
        if minute in {11, 13, 42}:
            service = "storefront" if minute == 11 else "payments"
            add_record(logs, "logs", {
                "observed_at": at(minute, 5), "service": service, "level": "INFO",
                "message": "Deployment completed" if minute == 11 else "Database pool configuration changed",
                "trace_id": None, "attributes": {"change_minute": minute},
            })
        if minute in {12, 22, 36}:
            service, message = {
                12: ("storefront", "Static asset cache invalidated after release"),
                22: ("email-worker", "Receipt delivery retried after mail provider timeout"),
                36: ("inventory", "Inventory cache miss; database fallback succeeded"),
            }[minute]
            add_record(logs, "logs", {
                "observed_at": at(minute, 28), "service": service, "level": "WARN",
                "message": message, "trace_id": None,
                "attributes": {"instance": f"{service}-2"},
            })
    write_jsonl("logs.jsonl", logs)


if __name__ == "__main__":
    main()
