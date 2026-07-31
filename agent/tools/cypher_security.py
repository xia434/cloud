"""Security policy for LLM-generated Cypher."""
from __future__ import annotations

import re


_WRITE_CYPHER_PATTERN = re.compile(
    r"\b(?:CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|FOREACH|LOAD\s+CSV|GRANT|DENY|REVOKE)\b",
    re.IGNORECASE,
)


def validate_read_only_cypher(query: str) -> None:
    """Reject generated Cypher that can mutate data or invoke procedures."""
    normalized = " ".join(query.strip().split())
    if not normalized:
        raise ValueError("生成的 Cypher 为空")
    if ";" in normalized:
        raise ValueError("禁止执行多条 Cypher 语句")
    if _WRITE_CYPHER_PATTERN.search(normalized) or re.search(r"\bCALL\b", normalized, re.IGNORECASE):
        raise ValueError("仅允许只读 Cypher 查询")
    if not re.match(r"^(?:MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN)\b", normalized, re.IGNORECASE):
        raise ValueError("Cypher 必须是只读查询")
