"""Explicit live smoke: paid providers, isolated local records, no confirmed actions.

Run from the repository root with --live. Never included in unittest discovery.
"""

import argparse
import json
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any

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
    SupportTask,
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
    ("cancel_followup", "Yes, cancel please", {"awaiting_confirmation"}),
    ("delivery", "Where is my 55–210mm lens?", {"answered"}),
    ("delivery_followup", "Has it shipped yet?", {"answered"}),
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


def smoke_app(repo, deps):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api.repository] = lambda: repo
    app.dependency_overrides[api.runtime] = lambda: deps
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Authorize paid model calls"
    )
    parser.add_argument("--limit", type=int, default=9, choices=range(1, 10))
    parser.add_argument("--only", nargs="+", choices=[q[0] for q in QUERIES])
    parser.add_argument("--output", type=Path, default=Path("/tmp/support-smoke.json"))
    parser.add_argument(
        "--restart-before-followup",
        action="store_true",
        help="Recreate API, repository and providers before continuation",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("--live is required; this command calls paid providers")
    selected = [q for q in QUERIES if not args.only or q[0] in args.only][: args.limit]
    prerequisites = {
        "cancel_followup": "eligibility",
        "delivery_followup": "delivery",
        "ticket_followup": "refund",
    }
    names = [q[0] for q in selected]
    for followup, prerequisite in prerequisites.items():
        if followup in names and prerequisite not in names:
            parser.error(f"{followup} requires {prerequisite} in the same invocation")

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
                SupportTask,
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
    with ExitStack() as stack:
        client = stack.enter_context(TestClient(app))
        login = client.post(base + "/sessions", json={"customer_id": "customer-alex"})
        login.raise_for_status()
        headers = {"Authorization": "Bearer " + login.json()["token"]}
        chat = None
        chats = {}
        for name, query, expected in selected:
            if name in prerequisites:
                chat = chats[prerequisites[name]]
                if args.restart_before_followup:
                    repo = SupportRepository(sessions)
                    deps = api.Runtime(
                        MockStore.load(),
                        LiveSupportModel(),
                        LiveJevJudge(),
                        index,
                        MockEmbeddingProvider(),
                    )
                    app = smoke_app(repo, deps)
                    client = stack.enter_context(TestClient(app))
            else:
                created = client.post(base + "/conversations", headers=headers)
                created.raise_for_status()
                chat = created.json()["conversation_id"]
            chats[name] = chat
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
            result: dict[str, Any] = (
                completed["result"] if completed else {"error": response.text}
            )
            passed = (
                result.get("disposition") in expected
                and result.get("stop_reason") != "provider_or_validation_failure"
                and result.get("receipt") is None
                and any(e["type"] == "started" for e in events)
            )
            if name in {"cancel", "cancel_followup", "address"}:
                passed = (
                    passed
                    and (result.get("pending_action") or {}).get("order_id")
                    == "order-1001"
                )
            if name == "refund":
                passed = (
                    passed
                    and (result.get("review_case") or {}).get("order_id")
                    == "order-1004"
                )
            if name == "cancel_followup":
                initial = next(
                    r["result"] for r in results if r["name"] == "eligibility"
                )
                passed = (
                    passed
                    and (result.get("task") or {}).get("task_id")
                    == (initial.get("task") or {}).get("task_id")
                    and any(
                        s["stage"] == "task_resumed" for s in result.get("steps", [])
                    )
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
