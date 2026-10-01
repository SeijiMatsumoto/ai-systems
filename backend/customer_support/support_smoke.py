"""Explicit live smoke: paid providers, isolated local records, no confirmed actions.

Run from the repository root with --live. Never included in unittest discovery.
"""

import argparse
import json
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.customer_support import api
from backend.customer_support.providers import LiveJevJudge, LiveSupportModel
from backend.customer_support.repository import SupportRepository
from backend.customer_support.retrieval import load_index
from backend.customer_support.store import MockStore
from backend.db.schemas import (
    Base,
    LlmRun,
    SupportCase,
    SupportConversation,
    SupportDemoSession,
    SupportOrder,
    SupportOutput,
    SupportProposal,
    SupportReceipt,
)
from backend.internal_knowledge_action.embedding import MockEmbeddingProvider

QUERIES = (
    ("orders", "What are my orders?", {"answered"}),
    (
        "eligibility",
        "Can I cancel my unshipped camera order?",
        {"answered", "awaiting_confirmation"},
    ),
    (
        "cancel",
        "Cancel the Canon EOS R50 order I placed on September 30.",
        {"awaiting_confirmation"},
    ),
    ("delivery", "Where is my 55–210mm lens?", {"answered"}),
    ("policy", "What is your return policy?", {"answered"}),
    (
        "compatibility",
        "Will the RF-S 55–210mm lens work with the EOS R50?",
        {"answered"},
    ),
    (
        "refund",
        "I want a refund for the EOS R8 delivered on September 15.",
        {"case_created"},
    ),
    ("ticket_followup", "What is the status of that ticket?", {"answered"}),
    (
        "address",
        "Change my shipping address to 123 Oak Street, Austin, 78701, US for the EOS R50 order.",
        {"awaiting_confirmation"},
    ),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Authorize paid model calls"
    )
    parser.add_argument("--limit", type=int, default=9, choices=range(1, 10))
    parser.add_argument("--only", nargs="+", choices=[q[0] for q in QUERIES])
    parser.add_argument("--output", type=Path, default=Path("/tmp/support-smoke.json"))
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this command calls paid providers")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables[model.__tablename__]
            for model in (
                LlmRun,
                SupportDemoSession,
                SupportConversation,
                SupportOutput,
                SupportOrder,
                SupportProposal,
                SupportReceipt,
                SupportCase,
            )
        ],
    )

    @contextmanager
    def sessions():
        with Session(engine, expire_on_commit=False) as db:
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    repo = SupportRepository(sessions)
    index = load_index()
    if index.embedding_model != "mock-embedding-v1":
        raise ValueError("Smoke expects the explicitly ingested mock policy index")
    deps = api.Runtime(
        MockStore.load(),
        LiveSupportModel(),
        LiveJevJudge(),
        index,
        MockEmbeddingProvider(),
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.repository] = lambda: repo
    app.dependency_overrides[api.runtime] = lambda: deps
    results = []
    base = "/agent/customer_support"
    with TestClient(app) as client:
        login = client.post(base + "/sessions", json={"customer_id": "customer-alex"})
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        chat = None
        selected = [q for q in QUERIES if not args.only or q[0] in args.only]
        for name, query, expected in selected[: args.limit]:
            if name != "ticket_followup":
                created = client.post(base + "/conversations", headers=headers)
                created.raise_for_status()
                chat = created.json()["conversation_id"]
            started = time.monotonic()
            response = client.post(
                base + f"/conversations/{chat}/messages/stream",
                headers=headers,
                json={"message": query},
            )
            events = [
                json.loads(line[6:])
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            completed = next((e for e in events if e["type"] == "completed"), None)
            result = completed["result"] if completed else {"error": response.text}
            passed = (
                result.get("disposition") in expected
                and result.get("stop_reason") != "provider_or_validation_failure"
            )
            record = {
                "name": name,
                "query": query,
                "passed": passed,
                "seconds": round(time.monotonic() - started, 2),
                "events": len(events),
                "result": result,
            }
            results.append(record)
            args.output.write_text(json.dumps(results, indent=2))
            print(
                json.dumps(
                    {
                        k: record[k]
                        for k in ("name", "query", "passed", "seconds", "events")
                    }
                    | {
                        "disposition": result.get("disposition"),
                        "stop_reason": result.get("stop_reason"),
                        "answer": result.get("answer"),
                        "usage": result.get("usage"),
                    }
                ),
                flush=True,
            )
    engine.dispose()
    print(
        f"Passed {sum(r['passed'] for r in results)}/{len(results)}. Saved {args.output}",
        flush=True,
    )
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
