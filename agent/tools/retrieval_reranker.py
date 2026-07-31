"""Dependency-free lexical reranking for Milvus candidates."""
from __future__ import annotations

import re
from typing import Any, Sequence


_CN_STOP_BIGRAMS = {
    "一个", "一般", "什么", "可以", "哪些", "如何", "怎么", "是否",
    "相关", "进行", "这个", "需要", "有什么",
}


def _query_terms(text: str) -> dict[str, float]:
    """Build weighted ASCII terms and Chinese bigrams without a tokenizer."""
    normalized = text.lower()
    terms: dict[str, float] = {}
    for token in re.findall(r"[a-z0-9][a-z0-9._-]+", normalized):
        terms[token] = max(terms.get(token, 0.0), 3.0)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", normalized):
        for index in range(len(sequence) - 1):
            token = sequence[index:index + 2]
            if token not in _CN_STOP_BIGRAMS:
                terms[token] = max(terms.get(token, 0.0), 1.0)
    return terms


def _document_text(document: Any) -> str:
    metadata = getattr(document, "metadata", {}) or {}
    return " ".join(
        str(value)
        for value in (
            getattr(document, "page_content", ""),
            metadata.get("source", ""),
            metadata.get("title", ""),
        )
        if value
    ).lower()


def _source_key(document: Any) -> str:
    metadata = getattr(document, "metadata", {}) or {}
    return str(metadata.get("source", "")).lower()


def _needs_source_diversity(query: str) -> bool:
    normalized = query.lower()
    selection_markers = ("推荐", "选型", "怎么选", "应该怎么", "部署")
    product_terms = ("ecs", "rds", "mysql", "vpc", "eip", "redis", "slb", "java")
    return (
        any(marker in normalized for marker in selection_markers)
        and sum(term in normalized for term in product_terms) >= 2
    )


def rerank_results(
    query: str,
    results: Sequence[tuple[Any, float]],
    limit: int = 3,
) -> list[tuple[Any, float]]:
    """Rerank semantic candidates using query coverage and original rank.

    Milvus score direction depends on the configured metric, so this function
    uses the stable original rank instead of comparing raw distance values.
    """
    if limit <= 0 or not results:
        return []

    terms = _query_terms(query)
    total_weight = sum(terms.values()) or 1.0
    ranked: list[tuple[float, int, tuple[Any, float]]] = []
    for index, result in enumerate(results):
        text = _document_text(result[0])
        source = _source_key(result[0])
        matched_weight = sum(weight for term, weight in terms.items() if term in text)
        lexical_coverage = matched_weight / total_weight
        semantic_rank_prior = 1.0 / (index + 1)
        domain_terms = ("ecs", "rds", "vpc", "eip", "redis", "mysql")
        source_alignment = 1.0 if any(
            term in query.lower() and term in source for term in domain_terms
        ) else 0.0
        combined_score = (
            0.60 * lexical_coverage
            + 0.25 * semantic_rank_prior
            + 0.15 * source_alignment
        )
        ranked.append((combined_score, -index, result))

    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    ordered = [item[2] for item in ranked]
    if not _needs_source_diversity(query):
        return ordered[:limit]

    selected: list[tuple[Any, float]] = []
    seen_sources: set[str] = set()
    for result in ordered:
        source = _source_key(result[0])
        if source and source in seen_sources:
            continue
        selected.append(result)
        if source:
            seen_sources.add(source)
        if len(selected) == limit:
            return selected
    for result in ordered:
        if result not in selected:
            selected.append(result)
        if len(selected) == limit:
            break
    return selected
