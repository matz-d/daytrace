from __future__ import annotations

import json
import re
import shlex
from collections import Counter, defaultdict
from difflib import unified_diff
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from common import ensure_datetime, extract_text, is_within_path, summarize_text


CLAUDE_SOURCE = "claude-history"
CODEX_SOURCE = "codex-history"
PREPARE_SOURCE = "skill-miner-prepare"
DETAIL_SOURCE = "skill-miner-detail"
RESEARCH_JUDGE_SOURCE = "skill-miner-research-judge"
PROPOSAL_SOURCE = "skill-miner-proposal"

MAX_SNIPPETS = 2
RAW_SNIPPET_LIMIT = 100
DEFAULT_TOP_N = 10
DEFAULT_MAX_UNCLUSTERED = 10
DEFAULT_GAP_HOURS = 8
DEFAULT_RESEARCH_REF_LIMIT = 5
OVERSIZED_CLUSTER_MIN_PACKETS = 8
OVERSIZED_CLUSTER_MIN_SHARE = 0.5

GENERIC_TASK_SHAPES = {
    "review_changes",
    "search_code",
    "summarize_findings",
    "inspect_files",
}

GENERIC_TOOL_SIGNATURES = {
    "bash",
    "cat",
    "ls",
    "nl",
    "read",
    "rg",
    "sed",
}

COMMON_COMMANDS = {
    "rg",
    "sed",
    "git",
    "pytest",
    "uv",
    "npm",
    "pnpm",
    "yarn",
    "cargo",
    "python",
    "python3",
    "bash",
    "zsh",
    "ls",
    "cat",
    "find",
    "grep",
    "make",
}

TASK_SHAPE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("prepare_report", ("daily report", "prepare report", "weekly report", "status report", "報告書", "レポート", "日報", "報告")),
    ("write_markdown", ("markdown", ".md", "readme", "draft", "記事", "ブログ", "write up")),
    ("debug_failure", ("root cause", "debug", "fix", "error", "bug", "failure", "failing", "修正", "不具合")),
    ("implement_feature", ("implement", "feature", "add", "build", "create", "ship", "実装", "追加")),
    ("edit_config", (".env", "config", "settings", "設定", "yaml", "json", "toml")),
    ("run_tests", ("pytest", "unit test", "integration test", "test", "tests", "spec", "検証")),
    ("review_changes", ("review", "findings", "pr", "diff", "指摘", "レビュー")),
    ("summarize_findings", ("findings", "severity", "summary", "要約", "まとめ")),
    ("search_code", ("rg", "grep", "search", "検索")),
    ("inspect_files", ("inspect", "read", "file", "確認", "読む")),
]

ARTIFACT_HINT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("claude-md", ("claude.md", "repo rule", "suggested rule", "local rule")),
    ("review", ("review", "findings", "pr", "指摘", "レビュー")),
    ("markdown", ("markdown", ".md", "readme", "記事", "日報")),
    ("report", ("report", "daily", "weekly", "summary", "レポート", "報告")),
    ("config", ("config", ".env", "yaml", "json", "設定")),
    ("code", ("python", "ts", "tsx", "js", "実装", "コード")),
]

REPEATED_RULE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("findings-first", ("findings-first", "findings first", "severity", "指摘", "severity順")),
    ("file-line-refs", ("file-line", "line refs", "line references", "line", "file", "行番号", "ファイル名")),
    ("concise-updates", ("concise", "short", "簡潔", "1-2 sentence", "same concise format")),
    ("tests-before-close", ("test", "pytest", "verification", "検証")),
]

MATCH_TEXT_NORMALIZATIONS: tuple[tuple[str, str], ...] = (
    ("pull request", "pr"),
    ("findings first", "findings-first"),
    ("findings-first", "findings-first"),
    ("same format", "same-format"),
    ("same findings format", "findings-first"),
    ("line refs", "file-line-refs"),
    ("line references", "file-line-refs"),
    ("file and line", "file-line-refs"),
    ("root cause", "debug"),
    ("failing", "failure"),
    ("write-up", "write up"),
    ("レポート", "report"),
    ("報告", "report"),
    ("日報", "daily report"),
    ("設定", "config"),
    ("実装", "implement"),
    ("修正", "fix"),
    ("不具合", "bug"),
)

TOKEN_SYNONYMS: dict[str, str] = {
    "summarise": "summarize",
    "summary": "report",
    "reporting": "report",
    "reports": "report",
    "reviewing": "review",
    "reviews": "review",
    "findings": "finding",
    "tests": "test",
    "testing": "test",
    "configs": "config",
    "settings": "config",
    "implemented": "implement",
    "implementing": "implement",
    "fixes": "fix",
    "fixed": "fix",
    "debugging": "debug",
}

DAYTRACE_RULES_SECTION = "## DayTrace Suggested Rules"
RULE_BULLET_PREFIX = "- "
CLAUDE_MD_FILENAME = "CLAUDE.md"

URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
PATH_PATTERN = re.compile(r"(/[^ \n\t`\"']+)")
WORD_PATTERN = re.compile(r"[A-Za-z0-9_./+-]+|[一-龥ぁ-んァ-ン]+")


def normalize_match_text(text: str) -> str:
    normalized = text.lower()
    for source, target in MATCH_TEXT_NORMALIZATIONS:
        normalized = normalized.replace(source, target)
    return normalized


def sanitize_url_domain(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return raw_url
    return f"{parsed.scheme}://{parsed.netloc}"


def mask_paths(text: str, workspace: str | None) -> str:
    masked = text
    if workspace:
        aliases = _workspace_aliases(str(Path(workspace).expanduser()))
        for alias in sorted(aliases, key=len, reverse=True):
            masked = masked.replace(alias, "[WORKSPACE]")
    masked = PATH_PATTERN.sub(_replace_path_token, masked)
    return masked


def _workspace_aliases(workspace: str) -> set[str]:
    aliases = {workspace}
    if workspace.startswith("/private/var/"):
        aliases.add(workspace[len("/private") :])
    elif workspace.startswith("/var/"):
        aliases.add(f"/private{workspace}")
    return aliases


def _replace_path_token(match: re.Match[str]) -> str:
    token = match.group(1)
    if token.startswith("[WORKSPACE]"):
        return token
    if token.startswith(("http://", "https://")):
        return token
    if token.startswith("/Users/") or token.startswith("/home/") or token.startswith("/tmp/") or token.startswith("/var/"):
        suffix = ""
        parts = token.split("/")
        if len(parts) > 3:
            suffix = "/" + "/".join(parts[-2:])
        return f"[PATH]{suffix}"
    return token


def compact_snippet(text: str, workspace: str | None, limit: int = RAW_SNIPPET_LIMIT) -> str:
    sanitized = URL_PATTERN.sub(lambda match: sanitize_url_domain(match.group(0)), text or "")
    sanitized = mask_paths(sanitized, workspace)
    return summarize_text(sanitized, limit)


def tokenize(value: str) -> set[str]:
    lowered = normalize_match_text(value)
    tokens = {TOKEN_SYNONYMS.get(token, token) for token in WORD_PATTERN.findall(lowered) if len(token) > 1}
    return {token for token in tokens if len(token) > 1}


def jaccard_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def extract_known_commands(text: str) -> list[str]:
    commands: list[str] = []
    for raw in re.findall(r"`([^`]+)`", text):
        try:
            tokens = shlex.split(raw)
        except ValueError:
            tokens = raw.split()
        if tokens:
            commands.append(tokens[0])
    for token in WORD_PATTERN.findall(text):
        lowered = token.lower()
        if lowered in COMMON_COMMANDS:
            commands.append(lowered)
    return commands


def build_claude_logical_packets(records: list[dict[str, Any]], gap_hours: int) -> list[dict[str, Any]]:
    logical_packets: list[dict[str, Any]] = []
    packet_records: list[dict[str, Any]] = []
    last_timestamp = None
    last_sidechain = None
    last_cwd = None

    def flush_packet() -> None:
        nonlocal packet_records
        if not packet_records:
            return
        user_messages: list[str] = []
        assistant_messages: list[str] = []
        tools: list[str] = []
        timestamps: list[str] = []
        cwd = None
        session_id = None
        is_sidechain = False
        for record in packet_records:
            timestamps.append(str(record.get("timestamp")))
            cwd = record.get("cwd") or cwd
            session_id = record.get("sessionId") or session_id
            is_sidechain = bool(record.get("isSidechain"))
            text = claude_message_text(record.get("message"))
            if record.get("type") == "user":
                user_messages.append(text)
            else:
                assistant_messages.append(text)
            message = record.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), list):
                for item in message["content"]:
                    if isinstance(item, dict) and item.get("type") == "tool_use":
                        name = str(item.get("name") or "").lower()
                        if name:
                            tools.append(name)
            tools.extend(extract_known_commands(text))

        logical_packets.append(
            {
                "started_at": earliest_iso_timestamp(timestamps),
                "ended_at": max(timestamps, key=compare_iso_timestamps, default=None),
                "timestamps": timestamps,
                "cwd": str(cwd) if cwd else None,
                "session_id": str(session_id) if session_id else None,
                "is_sidechain": is_sidechain,
                "user_messages": user_messages,
                "assistant_messages": assistant_messages,
                "tools": tools,
                "message_count": len(user_messages) + len(assistant_messages),
                "user_message_count": len(user_messages),
                "assistant_message_count": len(assistant_messages),
            }
        )
        packet_records = []

    for record in records:
        record_type = record.get("type")
        if record_type not in {"user", "assistant"}:
            continue
        if record.get("isMeta"):
            continue
        timestamp_value = record.get("timestamp")
        current_timestamp = ensure_datetime(timestamp_value)
        if current_timestamp is None:
            continue
        current_sidechain = bool(record.get("isSidechain"))
        current_cwd = record.get("cwd")
        should_split = False
        if packet_records and last_timestamp is not None:
            gap_seconds = current_timestamp.timestamp() - last_timestamp.timestamp()
            if gap_seconds >= gap_hours * 60 * 60:
                should_split = True
        if packet_records and last_sidechain is not None and current_sidechain != last_sidechain:
            should_split = True
        if packet_records and last_cwd is not None and current_cwd != last_cwd:
            should_split = True
        if should_split:
            flush_packet()
        packet_records.append(record)
        last_timestamp = current_timestamp
        last_sidechain = current_sidechain
        last_cwd = current_cwd

    flush_packet()
    return logical_packets


def infer_task_shapes(texts: list[str], tools: list[str]) -> list[str]:
    corpus = normalize_match_text(" ".join(texts + tools))
    specific: list[str] = []
    generic: list[str] = []
    for label, patterns in TASK_SHAPE_PATTERNS:
        if any(pattern.lower() in corpus for pattern in patterns):
            if label in GENERIC_TASK_SHAPES:
                generic.append(label)
            else:
                specific.append(label)
    if specific:
        return (specific[:3] + generic[: max(0, 3 - len(specific))])[:3]
    return generic[:3]


def infer_artifact_hints(texts: list[str], tools: list[str]) -> list[str]:
    corpus = normalize_match_text(" ".join(texts + tools))
    hints: list[str] = []
    for label, patterns in ARTIFACT_HINT_PATTERNS:
        if any(pattern.lower() in corpus for pattern in patterns):
            hints.append(label)
    return hints[:3]


def infer_repeated_rules(texts: list[str], workspace: str | None) -> list[dict[str, str]]:
    rules: list[dict[str, str]] = []
    seen: set[str] = set()
    for text in texts:
        lowered = normalize_match_text(text)
        for label, patterns in REPEATED_RULE_PATTERNS:
            if label in seen:
                continue
            if any(pattern.lower() in lowered for pattern in patterns):
                seen.add(label)
                rules.append({"normalized": label, "raw_snippet": compact_snippet(text, workspace)})
    return rules[:2]


def most_common_tool(tools: list[str]) -> tuple[str, list[str], int]:
    if not tools:
        return "none", [], 0
    counts = Counter(tool for tool in tools if tool)
    ordered = [name for name, _count in counts.most_common()]
    top_tool = ordered[0] if ordered else "none"
    return top_tool, ordered[:5], sum(counts.values())


def normalize_primary_intent(messages: list[str], workspace: str | None) -> str:
    for message in messages:
        snippet = compact_snippet(message, workspace)
        if snippet:
            return snippet
    return "No primary intent captured"


def append_unique_snippet(bucket: list[str], text: str, workspace: str | None) -> None:
    snippet = compact_snippet(text, workspace)
    if snippet and snippet not in bucket and len(bucket) < MAX_SNIPPETS:
        bucket.append(snippet)


def timestamp_to_epoch(value: Any) -> int:
    try:
        current = ensure_datetime(value)
    except (TypeError, ValueError):
        return 0
    if current is None:
        return 0
    return int(current.timestamp())


def compare_iso_timestamps(value: str | None) -> int:
    return timestamp_to_epoch(value)


def earliest_iso_timestamp(values: list[Any]) -> str | None:
    best: tuple[float, str] | None = None
    for value in values:
        try:
            current = ensure_datetime(value)
        except (TypeError, ValueError):
            continue
        if current is None:
            continue
        candidate = (current.timestamp(), current.isoformat())
        if best is None or candidate[0] < best[0]:
            best = candidate
    return best[1] if best else None


def build_claude_session_ref(file_path: str, packet_start: Any) -> str:
    return f"claude:{file_path}:{timestamp_to_epoch(packet_start)}"


def build_codex_session_ref(session_id: str, packet_start: Any) -> str:
    return f"codex:{session_id}:{timestamp_to_epoch(packet_start)}"


def parse_session_ref(value: str) -> tuple[str, str, int]:
    if value.startswith("claude:"):
        remainder = value[len("claude:") :]
        path, _, epoch = remainder.rpartition(":")
        if not path or not epoch:
            raise ValueError(f"Invalid Claude session_ref: {value}")
        return "claude", path, int(epoch)
    if value.startswith("codex:"):
        remainder = value[len("codex:") :]
        session_id, _, epoch = remainder.rpartition(":")
        if not session_id or not epoch:
            raise ValueError(f"Invalid Codex session_ref: {value}")
        return "codex", session_id, int(epoch)
    raise ValueError(f"Unknown session_ref prefix: {value}")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                record = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def claude_message_text(message: object) -> str:
    if not isinstance(message, dict):
        return extract_text(message)

    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
            elif item.get("type") == "thinking" and isinstance(item.get("thinking"), str):
                text_parts.append(item["thinking"])
            elif item.get("type") == "tool_use":
                name = item.get("name", "tool")
                text_parts.append(f"{name} tool call")
        return " ".join(part for part in text_parts if part)
    return extract_text(message)


def codex_message_text(payload: dict[str, Any]) -> str:
    return extract_text(payload.get("content"))


def codex_command_names(payload: dict[str, Any]) -> list[str]:
    names: list[str] = []
    function_name = str(payload.get("name") or "").strip()
    arguments = payload.get("arguments")
    if function_name and function_name != "exec_command":
        names.append(function_name)
    if function_name == "exec_command":
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else {}
        except json.JSONDecodeError:
            parsed = {}
        cmd = parsed.get("cmd")
        if isinstance(cmd, str):
            try:
                tokens = shlex.split(cmd)
            except ValueError:
                tokens = cmd.split()
            if tokens:
                names.append(tokens[0].lower())
    return names


def build_packet(
    *,
    packet_id: str,
    source: str,
    session_ref: str,
    session_id: str | None,
    workspace: str | None,
    timestamp: str | None,
    user_messages: list[str],
    assistant_messages: list[str],
    tools: list[str],
) -> dict[str, Any]:
    texts = user_messages + assistant_messages
    top_tool, tool_signature, tool_call_count = most_common_tool(tools)
    snippets: list[str] = []
    for message in user_messages + assistant_messages:
        append_unique_snippet(snippets, message, workspace)
    primary_intent = normalize_primary_intent(user_messages or texts, workspace)
    repeated_rules = infer_repeated_rules(assistant_messages or texts, workspace)
    return {
        "packet_id": packet_id,
        "source": source,
        "session_ref": session_ref,
        "session_id": session_id,
        "workspace": workspace,
        "timestamp": timestamp,
        "top_tool": top_tool,
        "tool_signature": tool_signature,
        "task_shape": infer_task_shapes(texts, tool_signature),
        "artifact_hints": infer_artifact_hints(texts, tool_signature),
        "primary_intent": primary_intent,
        "representative_snippets": snippets,
        "repeated_rules": repeated_rules,
        "support": {
            "message_count": len(user_messages) + len(assistant_messages),
            "tool_call_count": tool_call_count,
        },
    }


def candidate_label(packet: dict[str, Any]) -> str:
    task_shapes = packet.get("common_task_shapes") or packet.get("task_shape") or []
    artifact_hints = packet.get("artifact_hints") or []
    rule_hints = packet.get("rule_hints") or []
    if task_shapes:
        base = str(task_shapes[0]).replace("_", " ")
        descriptors = [str(value) for value in artifact_hints[:2] if value]
        if not descriptors:
            descriptors = [str(value) for value in rule_hints[:1] if value]
        if descriptors:
            return f"{base} ({', '.join(descriptors)})"
        return base
    intent = str(packet.get("primary_intent") or "").strip()
    if intent:
        return summarize_text(intent, 64)
    return "Unnamed candidate"


def candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, int, str]:
    return (
        float(candidate.get("score", 0.0)),
        int(candidate.get("support", {}).get("total_packets", 0)),
        str(candidate.get("label", "")),
    )


def packet_sort_key(packet: dict[str, Any]) -> tuple[int, str]:
    return (compare_iso_timestamps(packet.get("timestamp")), str(packet.get("packet_id", "")))


def stable_block_key(packet: dict[str, Any]) -> str:
    return stable_block_keys(packet)[0]


def stable_block_keys(packet: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    top_tool = str(packet.get("top_tool") or "none")
    task_shapes = packet.get("task_shape") or []
    artifact_hints = [str(value) for value in packet.get("artifact_hints", []) if value]
    repeated_rules = [str(item.get("normalized") or "") for item in packet.get("repeated_rules", []) if isinstance(item, dict)]
    first_shape = next((str(shape) for shape in task_shapes if shape not in GENERIC_TASK_SHAPES), "")
    if not first_shape and task_shapes:
        first_shape = str(task_shapes[0])
    first_artifact = artifact_hints[0] if artifact_hints else ""
    first_rule = repeated_rules[0] if repeated_rules else ""

    if first_shape and first_artifact:
        keys.append(f"task+artifact:{first_shape}:{first_artifact}")
    if first_shape and first_rule:
        keys.append(f"task+rule:{first_shape}:{first_rule}")
    if first_artifact and first_rule:
        keys.append(f"artifact+rule:{first_artifact}:{first_rule}")
    if first_shape:
        keys.append(f"task:{first_shape}")
    if first_artifact:
        keys.append(f"artifact:{first_artifact}")
    if first_rule:
        keys.append(f"rule:{first_rule}")
    if top_tool != "none" and top_tool not in GENERIC_TOOL_SIGNATURES:
        keys.append(f"tool:{top_tool}")
    elif top_tool != "none" and not keys:
        keys.append(f"tool:{top_tool}")
    if not keys:
        keys.append("misc")
    return list(dict.fromkeys(keys))


def candidate_score(support: dict[str, Any]) -> float:
    total_packets = int(support.get("total_packets", 0))
    source_count = 0
    if int(support.get("claude_packets", 0)) > 0:
        source_count += 1
    if int(support.get("codex_packets", 0)) > 0:
        source_count += 1
    recent_packets = int(support.get("recent_packets_7d", 0))
    diversity_bonus = 1.5 if source_count >= 2 else 0.0
    recency_bonus = min(recent_packets, 3) * 0.5
    return round(float(total_packets) + diversity_bonus + recency_bonus, 2)


def build_candidate_quality(candidate: dict[str, Any], total_packets_all: int) -> dict[str, Any]:
    support = candidate.get("support", {})
    total_packets = int(support.get("total_packets", 0))
    claude_packets = int(support.get("claude_packets", 0))
    codex_packets = int(support.get("codex_packets", 0))
    recent_packets = int(support.get("recent_packets_7d", 0))
    source_count = int(claude_packets > 0) + int(codex_packets > 0)
    task_shapes = [str(value) for value in candidate.get("common_task_shapes", []) if value]
    tool_signatures = [str(value) for value in candidate.get("common_tool_signatures", []) if value]
    rule_hints = [str(value) for value in candidate.get("rule_hints", []) if value]
    representative_examples = [str(value) for value in candidate.get("representative_examples", []) if value]

    quality_flags: list[str] = []
    cluster_share = (float(total_packets) / float(total_packets_all)) if total_packets_all > 0 else 0.0
    is_oversized_cluster = total_packets >= OVERSIZED_CLUSTER_MIN_PACKETS and cluster_share >= OVERSIZED_CLUSTER_MIN_SHARE
    if is_oversized_cluster:
        quality_flags.append("oversized_cluster")

    generic_task_shape = bool(task_shapes) and all(shape in GENERIC_TASK_SHAPES for shape in task_shapes[:3])
    if generic_task_shape:
        quality_flags.append("generic_task_shape")

    generic_tool_count = sum(1 for tool in tool_signatures[:4] if tool in GENERIC_TOOL_SIGNATURES)
    generic_tools = generic_tool_count >= 3
    if generic_tools:
        quality_flags.append("generic_tools")

    weak_semantic_cohesion = False
    if len(representative_examples) >= 2:
        left_tokens = tokenize(representative_examples[0])
        right_tokens = tokenize(representative_examples[1])
        weak_semantic_cohesion = jaccard_score(left_tokens, right_tokens) < 0.2
    if weak_semantic_cohesion:
        quality_flags.append("weak_semantic_cohesion")

    single_session_like = total_packets <= 1
    if single_session_like:
        quality_flags.append("single_session_like")

    score = 0
    if total_packets >= 4:
        score += 2
    elif total_packets >= 2:
        score += 1
    if source_count >= 2:
        score += 1
    if recent_packets >= 2:
        score += 1
    if rule_hints:
        score += 1
    if any(shape not in GENERIC_TASK_SHAPES for shape in task_shapes):
        score += 1
    if is_oversized_cluster:
        score -= 3
    if generic_task_shape:
        score -= 2
    if generic_tools:
        score -= 1
    if weak_semantic_cohesion:
        score -= 1
    if single_session_like:
        score -= 2

    confidence = "strong"
    if score < 1:
        confidence = "insufficient"
    elif score < 2:
        confidence = "weak"
    elif score < 4:
        confidence = "medium"

    generic_cluster = generic_task_shape and generic_tools
    proposal_ready = confidence in {"strong", "medium"} and not is_oversized_cluster and not weak_semantic_cohesion and not generic_cluster and not single_session_like

    triage_status = "ready"
    if single_session_like:
        triage_status = "rejected"
    elif proposal_ready:
        triage_status = "ready"
    elif is_oversized_cluster or weak_semantic_cohesion:
        triage_status = "needs_research"
    elif confidence == "insufficient":
        triage_status = "rejected"
    elif generic_cluster:
        triage_status = "needs_research"
    else:
        triage_status = "rejected"

    evidence_parts = [
        f"{total_packets} packets",
        f"Claude {claude_packets}",
        f"Codex {codex_packets}",
        f"recent7d {recent_packets}",
    ]
    if quality_flags:
        evidence_parts.append(f"flags: {', '.join(quality_flags)}")
    evidence_summary = " / ".join(evidence_parts)
    confidence_reason = evidence_summary if proposal_ready else f"{evidence_summary} / triage: {triage_status}"

    return {
        "confidence": confidence,
        "proposal_ready": proposal_ready,
        "triage_status": triage_status,
        "quality_flags": quality_flags,
        "evidence_summary": evidence_summary,
        "confidence_reason": confidence_reason,
    }


def annotate_unclustered_packet(packet: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(packet)
    quality_flags = ["unclustered_only", "single_session_like"]
    annotated.update(
        {
            "confidence": "insufficient",
            "proposal_ready": False,
            "triage_status": "rejected",
            "quality_flags": quality_flags,
            "evidence_summary": "1 packet / unclustered / not proposal-ready",
            "confidence_reason": "single observed packet only; keep as reference, not as a proposal candidate",
        }
    )
    return annotated


def build_research_targets(
    group_packets: list[dict[str, Any]],
    near_matches: list[dict[str, Any]],
    packet_lookup: dict[str, dict[str, Any]],
    limit: int = DEFAULT_RESEARCH_REF_LIMIT,
) -> list[dict[str, str]]:
    targets: list[dict[str, str]] = []
    seen_refs: set[str] = set()

    def add_target(session_ref: str | None, reason: str, packet_id: str | None = None) -> None:
        if not session_ref or session_ref in seen_refs or len(targets) >= limit:
            return
        seen_refs.add(session_ref)
        entry = {"session_ref": session_ref, "reason": reason}
        if packet_id:
            entry["packet_id"] = packet_id
        targets.append(entry)

    if group_packets:
        representative_packets = sorted(group_packets, key=lambda item: int(item.get("support", {}).get("message_count", 0)), reverse=True)
        add_target(representative_packets[0].get("session_ref"), "representative", representative_packets[0].get("packet_id"))
        if len(representative_packets) > 1:
            add_target(representative_packets[1].get("session_ref"), "representative", representative_packets[1].get("packet_id"))

        outlier_packet = None
        if len(group_packets) > 2:
            outlier_packet = min(
                group_packets,
                key=lambda item: len(tokenize(str(item.get("primary_intent") or ""))),
            )
        if outlier_packet is not None:
            add_target(outlier_packet.get("session_ref"), "outlier", outlier_packet.get("packet_id"))

    for match in near_matches:
        packet_id = str(match.get("packet_id") or "")
        matched_packet = packet_lookup.get(packet_id, {})
        add_target(matched_packet.get("session_ref"), "near_match", packet_id or None)
        if len(targets) >= limit:
            break

    if len(targets) < limit:
        for packet in group_packets:
            add_target(packet.get("session_ref"), "fallback", packet.get("packet_id"))
            if len(targets) >= limit:
                break

    return targets[:limit]


def build_research_brief(candidate: dict[str, Any]) -> dict[str, Any]:
    label = str(candidate.get("label") or "candidate")
    quality_flags = [str(value) for value in candidate.get("quality_flags", []) if value]
    objective = f"Validate whether '{label}' is one repeatable automation candidate or a merged cluster that should be split or rejected."
    questions = [
        "Do the target refs show one stable objective repeated across sessions?",
        "Are multiple distinct task types mixed inside this candidate?",
        "If the cluster should be split, what is the cleanest split axis?",
        "After reading the target refs, should this candidate be promoted to ready, split for re-triage, or rejected?",
    ]
    decision_rules = [
        "Promote to ready only if the sampled refs show one coherent objective with reusable steps.",
        "Reject if the sampled refs are mostly one-off tasks or context-specific requests.",
        "Split and re-triage if the sampled refs contain clearly different objectives that only share generic tools or review-style language.",
    ]
    if "oversized_cluster" in quality_flags:
        decision_rules.append("Because this is an oversized cluster, test split-first before forcing one proposal label.")
    if "generic_task_shape" in quality_flags or "generic_tools" in quality_flags:
        decision_rules.append("Do not treat shared review/search tooling alone as evidence of one reusable automation pattern.")
    if "weak_semantic_cohesion" in quality_flags:
        decision_rules.append("If representative examples point to different goals, keep the candidate out of ready state.")

    return {
        "objective": objective,
        "questions": questions,
        "decision_rules": decision_rules,
        "target_refs": candidate.get("research_targets", []),
    }


def build_detail_signal(detail: dict[str, Any]) -> dict[str, Any]:
    messages = detail.get("messages", [])
    texts = [str(message.get("text") or "") for message in messages if isinstance(message, dict) and message.get("text")]
    user_texts = [str(message.get("text") or "") for message in messages if isinstance(message, dict) and message.get("role") == "user"]
    assistant_texts = [str(message.get("text") or "") for message in messages if isinstance(message, dict) and message.get("role") == "assistant"]
    tools = [str(tool.get("name") or "") for tool in detail.get("tool_calls", []) if isinstance(tool, dict) and tool.get("name")]
    task_shapes = infer_task_shapes(texts, tools)
    artifact_hints = infer_artifact_hints(texts, tools)
    repeated_rules = infer_repeated_rules(assistant_texts or texts, str(detail.get("workspace") or ""))
    primary_intent = normalize_primary_intent(user_texts or texts, str(detail.get("workspace") or ""))
    return {
        "session_ref": detail.get("session_ref"),
        "task_shapes": task_shapes,
        "artifact_hints": artifact_hints,
        "repeated_rules": [item.get("normalized") for item in repeated_rules if item.get("normalized")],
        "tool_names": tools,
        "primary_intent": primary_intent,
    }


def _dominant_value_share(values: list[str]) -> tuple[str, int, float]:
    if not values:
        return "", 0, 0.0
    value, count = Counter(values).most_common(1)[0]
    return value, count, round(count / len(values), 3)


def _split_shape_groups(signals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        task_shapes = [str(value) for value in signal.get("task_shapes", []) if value]
        primary_shape = next((shape for shape in task_shapes if shape not in GENERIC_TASK_SHAPES), "")
        if primary_shape:
            groups[primary_shape].append(signal)
    return groups


def _average_token_overlap(signals: list[dict[str, Any]]) -> float:
    token_sets = [tokenize(str(signal.get("primary_intent") or "")) for signal in signals if signal.get("primary_intent")]
    pair_scores: list[float] = []
    for index, left in enumerate(token_sets):
        for right in token_sets[index + 1 :]:
            pair_scores.append(jaccard_score(left, right))
    return round(sum(pair_scores) / len(pair_scores), 3) if pair_scores else 0.0


def _build_subcluster_triage(split_groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    triage_items: list[dict[str, Any]] = []
    for shape, shape_signals in sorted(split_groups.items()):
        artifact_values = [signal["artifact_hints"][0] for signal in shape_signals if signal.get("artifact_hints")]
        dominant_artifact, _artifact_count, artifact_share = _dominant_value_share(artifact_values)
        overlap = _average_token_overlap(shape_signals)
        if len(shape_signals) < 2:
            triage_status = "rejected"
            confidence = "insufficient"
        elif overlap >= 0.14 or artifact_share >= 0.6:
            triage_status = "ready"
            confidence = "medium" if overlap < 0.2 else "strong"
        else:
            triage_status = "needs_research"
            confidence = "weak"
        triage_items.append(
            {
                "split_label": shape,
                "triage_status": triage_status,
                "confidence": confidence,
                "session_refs": [signal.get("session_ref") for signal in shape_signals if signal.get("session_ref")],
                "artifact_hint": dominant_artifact or None,
                "average_overlap": overlap,
            }
        )
    return triage_items


def _candidate_detail_refs(candidate: dict[str, Any]) -> set[str]:
    refs = {
        str(session_ref)
        for session_ref in candidate.get("session_refs", [])
        if str(session_ref or "").strip()
    }
    for target in candidate.get("research_targets", []):
        if isinstance(target, dict):
            session_ref = str(target.get("session_ref") or "").strip()
            if session_ref:
                refs.add(session_ref)
    return refs


def judge_research_candidate(candidate: dict[str, Any], details: list[dict[str, Any]]) -> dict[str, Any]:
    candidate_refs = _candidate_detail_refs(candidate)
    relevant_details = [
        detail
        for detail in details
        if isinstance(detail, dict)
        and (not candidate_refs or str(detail.get("session_ref") or "").strip() in candidate_refs)
    ]
    signals = [build_detail_signal(detail) for detail in relevant_details]
    if not signals:
        return {
            "recommendation": "reject_candidate",
            "proposed_triage_status": "rejected",
            "proposed_confidence": "insufficient",
            "summary": "No detail signals were available for research judgment.",
            "reasons": ["No detail records were resolved for the sampled refs."],
            "split_suggestions": [],
            "subcluster_triage": [],
            "detail_signals": [],
        }

    primary_shapes = [signal["task_shapes"][0] for signal in signals if signal.get("task_shapes")]
    distinct_primary_shapes = sorted(set(primary_shapes))
    non_generic_primary_shapes = sorted({shape for shape in distinct_primary_shapes if shape not in GENERIC_TASK_SHAPES})
    repeated_rule_count = sum(1 for signal in signals if signal.get("repeated_rules"))
    primary_artifacts = [signal["artifact_hints"][0] for signal in signals if signal.get("artifact_hints")]
    dominant_artifact, dominant_artifact_count, dominant_artifact_share = _dominant_value_share(primary_artifacts)
    token_sets = [tokenize(str(signal.get("primary_intent") or "")) for signal in signals if signal.get("primary_intent")]
    pair_scores: list[float] = []
    for index, left in enumerate(token_sets):
        for right in token_sets[index + 1 :]:
            pair_scores.append(jaccard_score(left, right))
    average_overlap = round(sum(pair_scores) / len(pair_scores), 3) if pair_scores else 0.0

    most_common_shape = ""
    shape_count = 0
    if primary_shapes:
        most_common_shape, shape_count = Counter(primary_shapes).most_common(1)[0]

    reasons: list[str] = []
    split_suggestions: list[str] = []
    recommendation = "reject_candidate"
    proposed_triage_status = "rejected"
    proposed_confidence = "insufficient"

    split_groups = _split_shape_groups(signals)
    eligible_split_groups = sorted(shape for shape, shape_signals in split_groups.items() if len(shape_signals) >= 2)
    subcluster_triage = _build_subcluster_triage(split_groups) if split_groups else []
    split_first = len(eligible_split_groups) >= 2 and average_overlap < 0.22
    promote_by_shape = shape_count >= 2 and average_overlap >= 0.12 and (repeated_rule_count >= 1 or most_common_shape not in GENERIC_TASK_SHAPES)
    promote_by_intent_artifact = (
        dominant_artifact_count >= 2
        and dominant_artifact_share >= 0.6
        and average_overlap >= 0.14
    )

    if split_first:
        recommendation = "split_candidate"
        proposed_triage_status = "needs_research"
        proposed_confidence = "weak"
        split_suggestions = eligible_split_groups
        reasons.append("Sampled refs contain multiple non-generic task objectives with low overlap; split-first is safer.")
    elif promote_by_shape or promote_by_intent_artifact:
        recommendation = "promote_ready"
        proposed_triage_status = "ready"
        proposed_confidence = "medium" if average_overlap < 0.2 else "strong"
        if promote_by_shape:
            reasons.append("Sampled refs show one repeatable objective with reusable steps.")
        else:
            reasons.append("Sampled refs stay consistent at the intent/artifact level even though task-shape evidence is weaker.")
    elif average_overlap < 0.08 and repeated_rule_count == 0:
        recommendation = "reject_candidate"
        proposed_triage_status = "rejected"
        proposed_confidence = "insufficient"
        reasons.append("Sampled refs do not show enough coherence to justify one automation candidate.")
    elif len(distinct_primary_shapes) >= 2 and average_overlap < 0.12:
        recommendation = "split_candidate"
        proposed_triage_status = "needs_research"
        proposed_confidence = "weak"
        split_suggestions = distinct_primary_shapes
        reasons.append("Sampled refs partially overlap but still mix multiple objectives.")
    else:
        recommendation = "reject_candidate"
        proposed_triage_status = "rejected"
        proposed_confidence = "weak"
        reasons.append("Sampled refs remain too generic to promote safely.")

    if "oversized_cluster" in candidate.get("quality_flags", []):
        if recommendation == "promote_ready":
            reasons.append("The original cluster was oversized, but sampled refs were coherent enough to recover to ready.")
        elif recommendation != "split_candidate":
            reasons.append("The original cluster was oversized, so split-first evidence was required before promotion.")
    if "generic_tools" in candidate.get("quality_flags", []) and recommendation != "promote_ready":
        reasons.append("Shared generic tools alone were not treated as reusable automation evidence.")
    if recommendation == "promote_ready" and dominant_artifact:
        reasons.append(f"Dominant artifact hint: {dominant_artifact} ({dominant_artifact_share:.2f} share).")

    summary = (
        f"recommendation={recommendation} / sampled_refs={len(signals)} / "
        f"primary_shapes={', '.join(distinct_primary_shapes) or 'none'} / "
        f"avg_overlap={average_overlap}"
    )
    return {
        "recommendation": recommendation,
        "proposed_triage_status": proposed_triage_status,
        "proposed_confidence": proposed_confidence,
        "summary": summary,
        "reasons": reasons,
        "split_suggestions": split_suggestions,
        "subcluster_triage": subcluster_triage,
        "detail_signals": signals,
    }


def _normalize_rule_line(line: str) -> str:
    stripped = re.sub(r"^\s*[-*]\s+", "", line.strip())
    stripped = re.sub(r"\s+", " ", stripped)
    return normalize_match_text(stripped)


def _split_section_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines()]


def _find_daytrace_section(lines: list[str]) -> tuple[int, int] | None:
    start = -1
    for index, line in enumerate(lines):
        if line.strip() == DAYTRACE_RULES_SECTION:
            start = index
            break
    if start < 0:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = index
            break
    return start, end


def _extract_existing_rule_lines(lines: list[str]) -> list[str]:
    return [line for line in lines if _normalize_rule_line(line)]


def _rule_polarity(normalized_line: str) -> str:
    negative_markers = ("never", "avoid", "do not", "don't", "禁止", "しない", "しないこと")
    return "negative" if any(marker in normalized_line for marker in negative_markers) else "positive"


def _is_conflicting_rule(existing_line: str, proposed_line: str) -> bool:
    existing_normalized = _normalize_rule_line(existing_line)
    proposed_normalized = _normalize_rule_line(proposed_line)
    if not existing_normalized or not proposed_normalized or existing_normalized == proposed_normalized:
        return False
    existing_tokens = tokenize(existing_normalized)
    proposed_tokens = tokenize(proposed_normalized)
    overlap = jaccard_score(existing_tokens, proposed_tokens)
    if overlap < 0.7:
        return False
    return _rule_polarity(existing_normalized) != _rule_polarity(proposed_normalized)


def _is_duplicate_rule(existing_line: str, proposed_line: str) -> bool:
    existing_normalized = _normalize_rule_line(existing_line)
    proposed_normalized = _normalize_rule_line(proposed_line)
    if not existing_normalized or not proposed_normalized:
        return False
    if existing_normalized == proposed_normalized:
        return True
    if _is_conflicting_rule(existing_line, proposed_line):
        return False
    overlap = jaccard_score(tokenize(existing_normalized), tokenize(proposed_normalized))
    return overlap >= 0.75


def _normalize_proposed_rules(proposed_rules: list[str] | str) -> list[str]:
    if isinstance(proposed_rules, str):
        raw_lines = [line.strip() for line in proposed_rules.splitlines()]
    else:
        raw_lines = [str(line).strip() for line in proposed_rules]
    normalized = [line for line in raw_lines if _normalize_rule_line(line)]
    return normalized


def build_claude_md_immediate_apply_preview(cwd: str | Path, proposed_rules: list[str] | str) -> dict[str, Any]:
    target_path = Path(cwd).expanduser().resolve() / CLAUDE_MD_FILENAME
    normalized_rules = _normalize_proposed_rules(proposed_rules)
    if not normalized_rules:
        return {
            "status": "empty_rules",
            "target_path": str(target_path),
            "applied": False,
            "preview": "",
            "rules_to_append": [],
        }
    candidate_lines = list(
        dict.fromkeys(RULE_BULLET_PREFIX + re.sub(r"^[-*]\s+", "", line) for line in normalized_rules)
    )
    if target_path.exists():
        current_text = target_path.read_text(encoding="utf-8")
        current_lines = _split_section_lines(current_text)
        section = _find_daytrace_section(current_lines)
    else:
        current_text = ""
        current_lines = []
        section = None
    existing_lines = _extract_existing_rule_lines(current_lines if section is None else current_lines[section[0] + 1 : section[1]])
    duplicates = [line for line in candidate_lines if any(_is_duplicate_rule(existing_line, line) for existing_line in existing_lines)]
    rules_to_append = [line for line in candidate_lines if line not in duplicates]

    conflict_pairs: list[dict[str, str]] = []
    for proposed_line in rules_to_append:
        for existing_line in existing_lines:
            if _is_conflicting_rule(existing_line, proposed_line):
                conflict_pairs.append({"existing": existing_line, "proposed": proposed_line})
                break
    for index, proposed_line in enumerate(rules_to_append):
        for prior_line in rules_to_append[:index]:
            if _is_conflicting_rule(prior_line, proposed_line):
                conflict_pairs.append({"existing": prior_line, "proposed": proposed_line})
                break

    if not rules_to_append:
        return {
            "status": "duplicate",
            "target_path": str(target_path),
            "applied": False,
            "preview": "",
            "duplicates": duplicates,
            "rules_to_append": [],
        }

    if section is None:
        updated_lines = current_lines[:]
        if updated_lines and updated_lines[-1].strip():
            updated_lines.append("")
        updated_lines.append(DAYTRACE_RULES_SECTION)
        updated_lines.append("")
        updated_lines.extend(rules_to_append)
    else:
        updated_lines = current_lines[: section[1]] + rules_to_append + current_lines[section[1] :]

    updated_text = "\n".join(updated_lines).rstrip() + "\n"
    preview = "".join(
        unified_diff(
            current_text.splitlines(keepends=True),
            updated_text.splitlines(keepends=True),
            fromfile="/dev/null" if not target_path.exists() else str(target_path),
            tofile=str(target_path),
        )
    )
    status = "conflict" if conflict_pairs else "ready_to_apply"
    return {
        "status": status,
        "target_path": str(target_path),
        "applied": False,
        "missing_file": not target_path.exists(),
        "preview": preview,
        "duplicates": duplicates,
        "conflicts": conflict_pairs,
        "rules_to_append": rules_to_append,
        "updated_text": updated_text,
    }


def apply_claude_md_immediate_rules(cwd: str | Path, proposed_rules: list[str] | str) -> dict[str, Any]:
    preview = build_claude_md_immediate_apply_preview(cwd, proposed_rules)
    if preview.get("status") != "ready_to_apply":
        return preview
    target_path = Path(str(preview["target_path"]))
    target_path.write_text(str(preview.get("updated_text") or ""), encoding="utf-8")
    applied = dict(preview)
    applied["status"] = "applied"
    applied["applied"] = True
    return applied


def merge_judgment_into_candidate(candidate: dict[str, Any], judgment_payload: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(candidate)
    if not judgment_payload:
        return merged
    judgment = judgment_payload.get("judgment", judgment_payload)
    if not isinstance(judgment, dict):
        return merged
    merged["research_judgment"] = judgment
    recommendation = str(judgment.get("recommendation") or "")
    proposed_triage_status = str(judgment.get("proposed_triage_status") or merged.get("triage_status") or "")
    proposed_confidence = str(judgment.get("proposed_confidence") or merged.get("confidence") or "")
    judgment_summary = str(judgment.get("summary") or "").strip()
    judgment_reasons = [str(reason).strip() for reason in judgment.get("reasons", []) if str(reason).strip()]
    merged["triage_status"] = proposed_triage_status
    merged["confidence"] = proposed_confidence
    merged["proposal_ready"] = recommendation == "promote_ready"
    if judgment_summary:
        merged["evidence_summary"] = judgment_summary
        merged["confidence_reason"] = judgment_summary
    elif judgment_reasons:
        merged["confidence_reason"] = judgment_reasons[0]
    if recommendation == "promote_ready":
        merged["quality_flags"] = [flag for flag in merged.get("quality_flags", []) if flag != "weak_semantic_cohesion"]
    return merged


def build_proposal_sections(prepare_payload: dict[str, Any], judgments_by_candidate_id: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    judgments_by_candidate_id = judgments_by_candidate_id or {}
    ready: list[dict[str, Any]] = []
    needs_research: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for raw_candidate in prepare_payload.get("candidates", []):
        if not isinstance(raw_candidate, dict):
            continue
        candidate_id = str(raw_candidate.get("candidate_id") or "")
        candidate = merge_judgment_into_candidate(raw_candidate, judgments_by_candidate_id.get(candidate_id))
        triage_status = str(candidate.get("triage_status") or "")
        if triage_status == "ready" and candidate.get("proposal_ready"):
            ready.append(candidate)
        elif triage_status == "needs_research":
            needs_research.append(candidate)
        else:
            rejected.append(candidate)

    for packet in prepare_payload.get("unclustered", []):
        if isinstance(packet, dict):
            rejected.append(annotate_unclustered_packet(packet))

    markdown = build_proposal_markdown(ready, needs_research, rejected)
    selection_prompt = "どの候補をドラフト化しますか？番号か候補名で指定してください。" if ready else None
    return {
        "ready": ready,
        "needs_research": needs_research,
        "rejected": rejected,
        "selection_prompt": selection_prompt,
        "markdown": markdown,
        "summary": {
            "ready_count": len(ready),
            "needs_research_count": len(needs_research),
            "rejected_count": len(rejected),
        },
    }


def build_proposal_markdown(ready: list[dict[str, Any]], needs_research: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("## 提案成立")
    if ready:
        for index, candidate in enumerate(ready, start=1):
            lines.extend(proposal_item_lines(index, candidate, include_classification=True))
    else:
        lines.append("今回は有力候補なし")

    lines.append("")
    lines.append("## 追加調査待ち")
    if needs_research:
        for index, candidate in enumerate(needs_research, start=1):
            lines.extend(proposal_item_lines(index, candidate, include_classification=False))
    else:
        lines.append("なし")

    lines.append("")
    lines.append("## 今回は見送り")
    if rejected:
        for index, candidate in enumerate(rejected[:5], start=1):
            lines.extend(rejected_item_lines(index, candidate))
    else:
        lines.append("なし")

    if ready:
        lines.append("")
        lines.append("どの候補をドラフト化しますか？番号か候補名で指定してください。")
    return "\n".join(lines)


def proposal_item_lines(index: int, candidate: dict[str, Any], *, include_classification: bool) -> list[str]:
    lines = [f"{index}. {candidate.get('label', 'Unnamed candidate')}"]
    if include_classification:
        lines.append(f"   分類: {candidate.get('suggested_kind', 'TBD')}")
    lines.append(f"   confidence: {candidate.get('confidence', 'unknown')}")
    lines.extend(build_evidence_chain_lines(candidate))
    judgment = candidate.get("research_judgment")
    if include_classification:
        lines.append(f"   期待効果: {candidate.get('label', 'この候補')} の再利用フローを安定化できる")
    elif isinstance(judgment, dict):
        lines.append(f"   保留理由: {judgment.get('summary', candidate.get('confidence_reason', '追加調査が必要'))}")
    else:
        lines.append(f"   保留理由: {candidate.get('confidence_reason', '追加調査が必要')}")
    return lines


def rejected_item_lines(index: int, candidate: dict[str, Any]) -> list[str]:
    label = candidate.get("label") or candidate.get("primary_intent") or candidate.get("packet_id") or "reference item"
    reason = candidate.get("confidence_reason") or candidate.get("evidence_summary") or "根拠不足"
    return [
        f"{index}. {label}",
        f"   理由: {reason}",
    ]


def build_evidence_chain_lines(candidate: dict[str, Any]) -> list[str]:
    lines = ["   根拠:"]
    evidence_items = candidate.get("evidence_items")
    if not isinstance(evidence_items, list) or not evidence_items:
        fallback = str(candidate.get("evidence_summary") or "n/a")
        lines.append(f"   - {fallback}")
        return lines

    for item in evidence_items[:3]:
        if not isinstance(item, dict):
            continue
        timestamp = str(item.get("timestamp") or "").strip()
        source = str(item.get("source") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not summary:
            summary = "summary unavailable"
        prefix_parts = [value for value in (timestamp, source) if value]
        prefix = " ".join(prefix_parts)
        if prefix:
            lines.append(f"   - {prefix}: {summary}")
        else:
            lines.append(f"   - {summary}")
    return lines


def recent_packet_count(timestamps: list[str], latest_timestamp: str | None) -> int:
    if not latest_timestamp:
        return 0
    latest = ensure_datetime(latest_timestamp)
    if latest is None:
        return 0
    threshold = latest.timestamp() - (7 * 24 * 60 * 60)
    count = 0
    for timestamp in timestamps:
        current = ensure_datetime(timestamp)
        if current and current.timestamp() >= threshold:
            count += 1
    return count


def workspace_matches(candidate: str | None, workspace: Path | None) -> bool:
    if workspace is None:
        return True
    return is_within_path(candidate, workspace)
