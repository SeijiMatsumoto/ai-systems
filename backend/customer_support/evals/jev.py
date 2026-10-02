"""Explicit, sequential Jev evaluation; replay saved observations without provider calls."""

import argparse
import asyncio
import json
import os
from pathlib import Path
from time import monotonic

from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator

from ..intent_classification import INTENT_PROMPT_VERSION, classification_input
from ..intent_policy import intent_branch
from .contracts import ClassifierCase, Observation

DATA = Path(__file__).with_name("jev_cases.json")


def load_cases():
    cases = [ClassifierCase.model_validate(row) for row in json.loads(DATA.read_text())]
    if len({case.name for case in cases}) != len(cases):
        raise ValueError("Duplicate case names")
    return cases


class ClassificationChecks(Evaluator):
    def evaluate(self, ctx):
        expected, observed = ctx.expected_output, ctx.output
        assert expected is not None
        if observed.judgment is None:
            return {
                "provider_success": False,
                "intent_match": False,
                "branch_match": False,
            }
        branch = intent_branch(observed.judgment)
        return {
            "provider_success": True,
            "intent_match": observed.judgment.intent == expected.intent,
            "branch_match": branch == expected.branch,
            "no_false_action": branch != "proposal" or expected.branch == "proposal",
            "no_unnecessary_clarification": branch != "clarify"
            or expected.branch == "clarify",
        }


async def evaluate(cases, classify):
    observations = []

    async def task(case):
        started = monotonic()
        try:
            # Schema/length validation precedes classification; no reference is authority.
            from ..contracts import ConversationTurn, SupportRequest
            from ..service import precheck

            state = precheck(
                SupportRequest(
                    conversation_id="eval-conversation", message=case.message
                ),
                [ConversationTurn.model_validate(turn) for turn in case.history],
            )
            state.update(
                conversation_context=case.context.model_dump(
                    mode="json", exclude={"saved_policy"}
                ),
                available_tasks=case.tasks,
            )
            async with asyncio.timeout(15):
                judgment = await classify(classification_input(state))
            observation = Observation(
                name=case.name, judgment=judgment, elapsed_seconds=monotonic() - started
            )
        except Exception as exc:  # noqa: BLE001 - preserve provider failure as an eval outcome
            observation = Observation(
                name=case.name,
                error=type(exc).__name__,
                elapsed_seconds=monotonic() - started,
            )
        observations.append(observation)
        return observation

    dataset = Dataset(
        name="support-jev-intent",
        cases=[
            Case(name=case.name, inputs=case, expected_output=case.expected)
            for case in cases
        ],
        evaluators=[ClassificationChecks()],
    )
    report = await dataset.evaluate(task, max_concurrency=1, progress=False)
    return report, observations


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--replay", type=Path)
    parser.add_argument(
        "--split", choices=["development", "holdout"], default="development"
    )
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument(
        "--output", type=Path, default=Path("/tmp/support-jev-eval.json")
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 10 or args.offset < 0 or (args.live and args.replay):
        parser.error("Use 1–10 sequential cases and either live or replay")
    cases = [case for case in load_cases() if case.split == args.split][
        args.offset : args.offset + args.limit
    ]
    if not args.live and not args.replay:
        print(
            f"Validated {len(load_cases())} labeled cases. No provider calls. Use --live explicitly or --replay saved observations."
        )
        return
    if args.replay:
        saved = {
            row["name"]: Observation.model_validate(row)
            for row in json.loads(args.replay.read_text())["observations"]
        }
        cases = [case for case in cases if case.name in saved]

        async def replay(state):
            case = next(
                case
                for case in cases
                if " ".join(case.message.split()) == state["message"]
                and case.context.model_dump(mode="json")["subjects"]
                == state["subjects"]
                and case.context.model_dump(mode="json")["pending"] == state["pending"]
                and [
                    {
                        "question": turn["question"][:500],
                        "answer": turn.get("answer", "")[:1500],
                    }
                    for turn in case.history[-4:]
                ]
                == state["recent_turns"]
            )
            observation = saved[case.name]
            if observation.judgment is None:
                raise RuntimeError(observation.error)
            return observation.judgment

        classify = replay
    else:
        from ..providers import LiveJevJudge

        classify = LiveJevJudge().classify
    if not cases:
        parser.error("No matching cases; check split, offset and replay names")
    report, observations = await evaluate(cases, classify)
    report.print(include_input=False, include_output=False)
    args.output.write_text(
        json.dumps(
            {
                "split": args.split,
                "mode": "live" if args.live else "replay",
                "classification_prompt_version": INTENT_PROMPT_VERSION
                if args.live
                else "historical observations",
                "case_results": [
                    {
                        "name": case.name,
                        "category": case.category,
                        "expected": case.expected.model_dump(mode="json"),
                        "application_branch": intent_branch(observation.judgment)
                        if observation.judgment
                        else None,
                        "intent_match": observation.judgment is not None
                        and observation.judgment.intent == case.expected.intent,
                        "branch_match": observation.judgment is not None
                        and intent_branch(observation.judgment) == case.expected.branch,
                        "false_action": observation.judgment is not None
                        and intent_branch(observation.judgment) == "proposal"
                        and case.expected.branch != "proposal",
                        "unnecessary_clarification": observation.judgment is not None
                        and intent_branch(observation.judgment) == "clarify"
                        and case.expected.branch != "clarify",
                    }
                    for case, observation in zip(cases, observations, strict=True)
                ],
                "observations": [item.model_dump(mode="json") for item in observations],
            },
            indent=2,
        )
    )
    print(f"Saved raw scores, margin, usage and latency to {args.output}")


if __name__ == "__main__":
    os.environ["LOGFIRE_SEND_TO_LOGFIRE"] = "false"
    asyncio.run(main())
