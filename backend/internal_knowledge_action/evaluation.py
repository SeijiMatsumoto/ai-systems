"""Small labeled retrieval checks; mock vectors measure wiring, not model quality."""

import json
from pathlib import Path

from pydantic import BaseModel, Field

from backend.internal_knowledge_action.contracts import (
    IndexSnapshot,
    KnowledgeQuestionRequest,
    RetrievalFixture,
)
from backend.internal_knowledge_action.embedding import EmbeddingProvider
from backend.internal_knowledge_action.retrieval import retrieve_knowledge

EVAL_PATH = Path(__file__).parent / "fixtures" / "retrieval_eval_v3.json"


class RetrievalCase(BaseModel):
    persona_id: str
    question: str
    expected_source_ids: list[str]


class RetrievalDataset(BaseModel):
    version: str
    cases: list[RetrievalCase] = Field(min_length=1)


class EvaluationResult(BaseModel):
    dataset_version: str
    case_count: int
    recall_at_3: float
    precision_among_returned: float
    top_1_accuracy: float
    no_answer_accuracy: float
    unauthorized_source_count: int


def evaluate_retrieval(
    fixture: RetrievalFixture,
    index: IndexSnapshot,
    embedder: EmbeddingProvider,
    dataset: RetrievalDataset,
) -> EvaluationResult:
    recall_total = 0.0
    precision_total = 0.0
    top_one_total = 0
    no_answer_total = 0
    no_answer_count = 0
    unauthorized = 0
    for case in dataset.cases:
        result = retrieve_knowledge(
            KnowledgeQuestionRequest(
                persona_id=case.persona_id, question=case.question
            ),
            fixture,
            index,
            embedder,
        )
        found = [item.locator.source_id for item in result.ranked_excerpts]
        allowed = set(result.authorized_source_ids)
        seen = found + [
            item.source_id
            for item in result.lexical_candidates + result.vector_candidates
        ]
        unauthorized += len(
            [source_id for source_id in seen if source_id not in allowed]
        )
        expected = set(case.expected_source_ids)
        if expected:
            recall_total += len(expected & set(found)) / len(expected)
            precision_total += (
                len(expected & set(found)) / len(set(found)) if found else 0.0
            )
            top_one_total += int(bool(found) and found[0] in expected)
        else:
            no_answer_count += 1
            no_answer_total += int(not found)
    answer_cases = len(dataset.cases) - no_answer_count
    return EvaluationResult(
        dataset_version=dataset.version,
        case_count=len(dataset.cases),
        recall_at_3=round(recall_total / answer_cases, 3) if answer_cases else 0.0,
        precision_among_returned=round(precision_total / answer_cases, 3)
        if answer_cases
        else 0.0,
        top_1_accuracy=round(top_one_total / answer_cases, 3) if answer_cases else 0.0,
        no_answer_accuracy=round(no_answer_total / no_answer_count, 3)
        if no_answer_count
        else 0.0,
        unauthorized_source_count=unauthorized,
    )


def load_dataset(path: Path = EVAL_PATH) -> RetrievalDataset:
    return RetrievalDataset.model_validate(json.loads(path.read_text()))
