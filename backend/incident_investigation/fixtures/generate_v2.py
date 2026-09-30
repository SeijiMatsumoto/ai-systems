"""Derive the replay fixture from v1 and add labeled nonincident error bursts."""

import json
from pathlib import Path

ROOT = Path(__file__).parent
SOURCE = ROOT / "v1"
OUT = ROOT / "v2"
DATA_FILES = ("logs", "metrics", "traces", "changes")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    manifest["fixture_id"] = "checkout-stream-detection-2026-04-14"
    manifest["version"] = 2
    del manifest["alert"]  # This replay must discover incidents from logs.
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    # Evaluation labels are kept separate from the replayed telemetry.
    labels = {
        "candidate_cases": [
            {
                "service": "checkout",
                "message": "Payment authorization timed out; order failed",
                "incident": True,
            },
            {
                "service": "inventory",
                "message": "Inventory cache refresh failed; stale cache served",
                "incident": False,
            },
        ],
        "below_threshold_cases": [
            {
                "service": "email-worker",
                "message": "Receipt delivery failed; retry scheduled",
            }
        ],
    }
    (OUT / "expected_detection.json").write_text(
        json.dumps(labels, indent=2) + "\n", encoding="utf-8"
    )

    for name in DATA_FILES:
        records = [
            json.loads(line)
            for line in (SOURCE / f"{name}.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        for record in records:
            record["locator"] = record["locator"].replace(
                "fixtures/v1/", "fixtures/v2/"
            )
        if name == "logs":
            additions = [
                # Two independent mail retries: below the candidate threshold.
                (
                    24,
                    31,
                    "email-worker",
                    "ERROR",
                    "Receipt delivery failed; retry scheduled",
                    "mail-0024",
                ),
                (
                    25,
                    31,
                    "email-worker",
                    "ERROR",
                    "Receipt delivery failed; retry scheduled",
                    "mail-0025",
                ),
                # A repeated inventory error with successful fallback. This should become
                # a candidate, then be judged as nonincident by the later Jev gate.
                (
                    34,
                    31,
                    "inventory",
                    "ERROR",
                    "Inventory cache refresh failed; stale cache served",
                    "cache-0034",
                ),
                (
                    35,
                    31,
                    "inventory",
                    "ERROR",
                    "Inventory cache refresh failed; stale cache served",
                    "cache-0035",
                ),
                (
                    36,
                    31,
                    "inventory",
                    "ERROR",
                    "Inventory cache refresh failed; stale cache served",
                    "cache-0036",
                ),
            ]
            for minute, second, service, level, message, request_id in additions:
                evidence_id = f"logs-{len(records) + 1:04d}"
                records.append(
                    {
                        "attributes": {
                            "instance": f"{service}-2",
                            "request_id": request_id,
                        },
                        "evidence_id": evidence_id,
                        "level": level,
                        "locator": f"fixtures/v2/logs.jsonl#{evidence_id}",
                        "message": message,
                        "observed_at": f"2026-04-14T14:{minute:02d}:{second:02d}Z",
                        "service": service,
                        "trace_id": None,
                    }
                )
        (OUT / f"{name}.jsonl").write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
