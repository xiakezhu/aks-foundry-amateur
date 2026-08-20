"""Phase A tool filter for Work IQ MCP verbs.

Toolbox require_approval is not HITL. Hide write verbs from the model until Phase B.
"""

from __future__ import annotations

# Names as in the Work IQ MCP overview. Matching is case-insensitive and
# ignores a server-label prefix (e.g. workiq_fetch).
PHASE_A_ALLOW = frozenset(
    {
        "fetch",
        "fetch_blob",
        "ask",
        "list_agents",
        "get_schema",
        "search_paths",
        "call_function",
    }
)

PHASE_A_DENY = frozenset(
    {
        "create_entity",
        "update_entity",
        "delete_entity",
        "do_action",
    }
)


def canonical_tool_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if "_" in lowered:
        prefix, _, rest = lowered.partition("_")
        if rest in PHASE_A_ALLOW or rest in PHASE_A_DENY:
            return rest
    return lowered


def is_phase_a_allowed(name: str) -> bool:
    canon = canonical_tool_name(name)
    if canon in PHASE_A_DENY:
        return False
    if canon in PHASE_A_ALLOW:
        return True
    return False


def filter_phase_a_tools(tools: list[dict]) -> list[dict]:
    """Keep Phase A tools; drop writes and unknown verbs."""
    kept = []
    for tool in tools:
        name = tool.get("name") or tool.get("tool") or ""
        if is_phase_a_allowed(str(name)):
            kept.append(tool)
    return kept
