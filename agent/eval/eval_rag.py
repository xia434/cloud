"""Official Ragas evaluation for the real ProductAgent workflow.

The collector executes the compiled LangGraph, captures actual RAG tool outputs
and the final ProductAgent response, then evaluates those samples with Ragas.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


AGENT_ROOT = Path(__file__).parent.parent
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

load_dotenv(AGENT_ROOT / ".env")
os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")

from eval.dataset import get_dataset


EVAL_OUTPUT_DIR = AGENT_ROOT / "eval" / "results"
EVAL_OUTPUT_DIR.mkdir(exist_ok=True)

METRIC_NAMES = (
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)

DEFAULT_THRESHOLDS = {
    "faithfulness": 0.75,
    "answer_relevancy": 0.70,
    "context_precision": 0.65,
    "context_recall": 0.60,
}


def _build_llm() -> Any:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        model=os.getenv("RAGAS_MODEL", os.getenv("MODEL", "qwen-plus")),
        base_url=os.getenv(
            "BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        temperature=0,
    )


def _build_embeddings() -> Any:
    from langchain_community.embeddings import DashScopeEmbeddings

    return DashScopeEmbeddings(
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-v2"),
    )


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    content = getattr(value, "content", "")
    return content.strip() if isinstance(content, str) else ""


def _extract_node_answer(output: Any) -> str:
    if not isinstance(output, dict):
        return ""
    messages = output.get("messages") or []
    return _as_text(messages[-1]) if messages else ""


def _extract_sources(tool_name: str, context: str) -> list[str]:
    if tool_name == "query_knowledge_graph":
        return ["knowledge_graph"]
    return [source.strip() for source in re.findall(r"【来源:\s*([^】]+)】", context)]


def _split_tool_context(tool_name: str, context: str) -> list[str]:
    """Preserve vector search chunks as separate Ragas contexts."""
    if tool_name != "query_vector_db":
        return [context]
    parts = re.split(r"(?=【来源:\s*[^】]+】)", context)
    return [part.strip() for part in parts if part.strip()]


async def _collect_agent_sample(
    graph: Any,
    item: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    """Execute the actual graph and capture ProductAgent evidence."""
    question = item["question"]
    state = {
        "messages": [("user", question)],
        "user_id": "ragas_eval_user",
        "session_id": f"ragas_eval_{index}",
        "memory_context": "",
        "next_agent": "",
        "metadata": {},
    }
    config = {
        "configurable": {
            "user_id": "ragas_eval_user",
            "thread_id": f"ragas-eval:{index}",
        },
        "metadata": {"evaluation": True, "dataset_index": index},
    }

    answer = ""
    route = ""
    contexts: list[str] = []
    sources: list[str] = []
    tool_calls: list[str] = []

    async for event in graph.astream_events(state, config=config, version="v2"):
        kind = event.get("event")
        name = event.get("name", "")
        data = event.get("data") or {}

        if kind == "on_chain_end" and name == "orchestrator":
            output = data.get("output")
            if isinstance(output, dict):
                route = str(output.get("next_agent", ""))
        elif kind == "on_tool_end":
            tool_context = _as_text(data.get("output"))
            if tool_context:
                contexts.extend(_split_tool_context(name, tool_context))
                sources.extend(_extract_sources(name, tool_context))
                tool_calls.append(name)
        elif kind == "on_chain_end" and name in {
            "product_agent",
            "recommendation_agent",
        }:
            answer = _extract_node_answer(data.get("output")) or answer

    return {
        "question": question,
        "answer": answer,
        "contexts": contexts,
        "retrieval_sources": sources,
        "ground_truth": item["ground_truth"],
        "expected_sources": item["relevant_sources"],
        "expected_agent": item["expected_agent"],
        "route": route,
        "tool_calls": tool_calls,
    }


async def _run_agent_pipeline(dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from core.workflow.graph_manager import AgentGraphManager

    graph = AgentGraphManager().build_graph()
    results = []
    for index, item in enumerate(dataset, 1):
        print(f"[{index}/{len(dataset)}] ProductAgent: {item['question']}")
        sample = await _collect_agent_sample(graph, item, index)
        results.append(sample)
        print(
            f"  route={sample['route']} tools={sample['tool_calls']} "
            f"contexts={len(sample['contexts'])} answer_chars={len(sample['answer'])}"
        )
    return results


def _compute_retrieval_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    per_item = []
    full = partial = missed = 0
    for result in results:
        expected = set(result["expected_sources"])
        actual = {os.path.basename(source) for source in result["retrieval_sources"]}
        intersection = expected & actual
        if len(intersection) == len(expected):
            status = "full"
            full += 1
        elif intersection:
            status = "partial"
            partial += 1
        else:
            status = "miss"
            missed += 1
        per_item.append(
            {
                "question": result["question"],
                "expected": sorted(expected),
                "actual": sorted(actual),
                "status": status,
            }
        )
    total = len(results)
    weighted = (full + 0.5 * partial) / total if total else 0.0
    return {
        "total": total,
        "fully_covered": full,
        "partially_covered": partial,
        "missed": missed,
        "coverage_rate": weighted,
        "per_item": per_item,
    }


def _compute_route_accuracy(results: list[dict[str, Any]]) -> dict[str, Any]:
    items = [
        {
            "question": result["question"],
            "expected": result["expected_agent"],
            "actual": result["route"],
            "passed": result["expected_agent"] == result["route"],
        }
        for result in results
    ]
    passed = sum(1 for item in items if item["passed"])
    return {
        "passed": passed,
        "total": len(items),
        "accuracy": passed / len(items) if items else 0.0,
        "per_item": items,
    }


def _install_ragas_langchain_compat() -> None:
    """Shim a removed optional VertexAI import used by Ragas 0.4.x.

    Ragas imports the legacy class unconditionally although this project uses
    Qwen through ChatOpenAI. The placeholder is never instantiated; it avoids
    downgrading langchain-community solely for an unused provider.
    """
    module_name = "langchain_community.chat_models.vertexai"
    try:
        __import__(module_name)
    except ModuleNotFoundError:
        module = types.ModuleType(module_name)
        module.ChatVertexAI = type("ChatVertexAI", (), {})
        sys.modules[module_name] = module


def _build_ragas_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "user_input": result["question"],
            "response": result["answer"],
            "retrieved_contexts": result["contexts"],
            "reference": result["ground_truth"],
        }
        for result in results
    ]


def _evaluate_with_ragas(results: list[dict[str, Any]]) -> dict[str, Any]:
    _install_ragas_langchain_compat()

    import ragas
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics._answer_relevance import AnswerRelevancy
    from ragas.metrics._context_precision import ContextPrecision
    from ragas.metrics._context_recall import ContextRecall
    from ragas.metrics._faithfulness import Faithfulness
    from ragas.run_config import RunConfig

    llm = LangchainLLMWrapper(_build_llm())
    embeddings = LangchainEmbeddingsWrapper(_build_embeddings())
    metrics = [
        Faithfulness(llm=llm),
        # Qwen's OpenAI-compatible endpoint returns one generation per call.
        AnswerRelevancy(llm=llm, embeddings=embeddings, strictness=1),
        ContextPrecision(llm=llm),
        ContextRecall(llm=llm),
    ]
    evaluation_dataset = EvaluationDataset.from_list(_build_ragas_rows(results))
    run_config = RunConfig(
        timeout=int(os.getenv("RAGAS_TIMEOUT_SECONDS", "180")),
        max_retries=2,
        max_wait=30,
        max_workers=int(os.getenv("RAGAS_MAX_WORKERS", "4")),
    )
    evaluation = evaluate(
        dataset=evaluation_dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
        experiment_name="cloud-agent-product-rag",
        raise_exceptions=False,
        show_progress=True,
    )
    rows = evaluation.to_pandas().to_dict(orient="records")

    per_item = []
    summary = {}
    for metric in METRIC_NAMES:
        values = [float(row[metric]) for row in rows if not math.isnan(float(row[metric]))]
        summary[metric] = sum(values) / len(values) if values else None
    for result, row in zip(results, rows):
        per_item.append(
            {
                "question": result["question"],
                **{
                    metric: (
                        None
                        if math.isnan(float(row[metric]))
                        else float(row[metric])
                    )
                    for metric in METRIC_NAMES
                },
            }
        )
    return {
        "engine": "official_ragas",
        "ragas_version": ragas.__version__,
        "summary": summary,
        "per_item": per_item,
    }


def _load_thresholds() -> dict[str, float]:
    return {
        metric: float(
            os.getenv(f"RAGAS_MIN_{metric.upper()}", str(default_value))
        )
        for metric, default_value in DEFAULT_THRESHOLDS.items()
    }


def _build_quality_gate(
    scores: dict[str, float | None],
    thresholds: dict[str, float],
) -> dict[str, Any]:
    checks = {
        metric: {
            "score": scores.get(metric),
            "minimum": minimum,
            "passed": scores.get(metric) is not None
            and float(scores[metric]) >= minimum,
        }
        for metric, minimum in thresholds.items()
    }
    return {"passed": all(check["passed"] for check in checks.values()), "checks": checks}


async def main(enforce_thresholds: bool = False) -> dict[str, Any]:
    dataset = get_dataset()
    print(f"Official Ragas evaluation: {len(dataset)} samples")
    results = await _run_agent_pipeline(dataset)
    coverage = _compute_retrieval_coverage(results)
    route_accuracy = _compute_route_accuracy(results)
    ragas_result = await asyncio.to_thread(_evaluate_with_ragas, results)
    thresholds = _load_thresholds()
    quality_gate = _build_quality_gate(ragas_result["summary"], thresholds)

    report = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "evaluator": "official_ragas",
            "ragas_version": ragas_result["ragas_version"],
            "model": os.getenv("RAGAS_MODEL", os.getenv("MODEL", "qwen-plus")),
            "embedding_model": os.getenv("EMBEDDING_MODEL", "text-embedding-v2"),
            "pipeline": "compiled_langgraph_rag_agents",
        },
        "summary": {
            "total_questions": len(dataset),
            "retrieval_coverage": coverage,
            "route_accuracy": route_accuracy,
            "ragas_metrics": ragas_result["summary"],
            "quality_gate": quality_gate,
        },
        "metric_details": ragas_result["per_item"],
        "details": results,
    }
    output_file = EVAL_OUTPUT_DIR / "eval_report_latest.json"
    output_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report: {output_file}")
    if enforce_thresholds and not quality_gate["passed"]:
        raise SystemExit(2)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate ProductAgent with official Ragas")
    parser.add_argument(
        "--enforce-thresholds",
        action="store_true",
        help="Exit with code 2 when any quality threshold is not met",
    )
    args = parser.parse_args()
    asyncio.run(main(enforce_thresholds=args.enforce_thresholds))
