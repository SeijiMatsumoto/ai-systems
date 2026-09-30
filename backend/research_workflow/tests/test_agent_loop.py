"""Exercise research source selection and citation through a fake model."""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from backend.research_workflow.agent.agent import agent, run_research_briefing_agent
from backend.research_workflow.contracts import (
    BriefingRequest,
    ExtractedWebPage,
    WebSearchResult,
)


class ResearchAgentLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_extract_then_cite_exact_passage(self) -> None:
        as_of = datetime.now(timezone.utc) - timedelta(minutes=1)
        search_result = WebSearchResult(
            result_id="tavily:apple",
            title="Apple describes product execution risk",
            source_url="https://example.com/apple-risk",
            summary="Apple reported product execution risks.",
            published_at=as_of - timedelta(days=1),
            date_precision="instant",
        )
        rows = [
            {
                "chunk_id": "00000000-0000-0000-0000-000000000002",
                "reference_id": search_result.result_id,
                "chunk_index": 0,
                "document_id": "00000000-0000-0000-0000-000000000001",
                "document_type": "article",
                "content": "Apple reported that launch delays could affect product execution and customer demand in the coming year.",
                "content_quality": "full_text",
                "similarity": 0.0,
                "title": search_result.title,
                "source_url": search_result.source_url,
                "published_at": search_result.published_at,
            }
        ]
        observed_ids: list[str] = []

        async def model_function(messages, info):
            if len(messages) == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "search_web",
                            {
                                "inputs": {
                                    "query": "product execution risk",
                                    "topic": "news",
                                }
                            },
                        )
                    ]
                )
            if len(messages) == 3:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            "inspect_web_results",
                            {
                                "inputs": {
                                    "result_ids": [search_result.result_id],
                                    "focus": "product execution risk",
                                }
                            },
                        )
                    ]
                )
            evidence_id = next(iter(observed_ids))
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {
                            "executive_summary": "Apple described a product execution risk.",
                            "key_findings": [
                                {
                                    "statement": "Apple said launch delays could affect product execution.",
                                    "claim_type": "fact",
                                    "confidence": 2,
                                    "evidence_ids": [evidence_id],
                                }
                            ],
                            "outlook": "The risk depends on future launch execution.",
                            "limitations": [],
                        },
                    )
                ]
            )

        def persist(*args, **kwargs):
            from backend.research_workflow.agent.evidence import (
                build_document_evidence_candidates,
            )

            observed_ids.extend(
                candidate.evidence_id
                for candidate in build_document_evidence_candidates(
                    "product execution risk",
                    rows,
                    max_candidates=1,
                    require_term_overlap=True,
                )
            )
            return rows

        request = BriefingRequest(
            symbol="AAPL",
            as_of=as_of,
            research_question="What product execution risks did Apple describe recently?",
            audience="investors",
            time_horizon="12m",
        )
        with (
            agent.override(model=FunctionModel(model_function)),
            patch(
                "backend.research_workflow.agent.agent.tavily.search",
                return_value=([search_result], 0, {"credits": 1}),
            ),
            patch(
                "backend.research_workflow.agent.agent.tavily.extract",
                return_value=(
                    [
                        ExtractedWebPage(
                            source_url=search_result.source_url,
                            content="extracted source",
                        )
                    ],
                    [],
                    {"credits": 2},
                ),
            ),
            patch(
                "backend.research_workflow.agent.agent.persist_inspected_web_page",
                side_effect=persist,
            ),
        ):
            execution = await run_research_briefing_agent(
                request,
                {"company_snapshot": {"company_name": "Apple Inc."}},
                {},
                {},
                uuid4(),
            )
        self.assertEqual(
            execution.result.output.key_findings[0].evidence_ids, observed_ids
        )
        self.assertEqual(len(execution.evidence_catalog), 1)
