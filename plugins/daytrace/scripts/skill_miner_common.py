from __future__ import annotations

import json
import re
import shlex
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from common import ensure_datetime, extract_text, is_within_path, summarize_text


CLAUDE_SOURCE = "claude-history"
CODEX_SOURCE = "codex-history"
PREPARE_SOURCE = "skill-miner-prepare"
DETAIL_SOURCE = "skill-miner-detail"

MAX_SNIPPETS = 2
RAW_SNIPPET_LIMIT = 100
DEFAULT_TOP_N = 10
DEFAULT_MAX_UNCLUSTERED = 10
DEFAULT_GAP_HOURS = 8

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
    ("review_changes", ("review", "findings", "pr", "diff", "指摘", "レビュー")),
    ("summarize_findings", ("findings", "severity", "summary", "要約", "まとめ")),
    ("search_code", ("rg", "grep", "search", "検索")),
    ("inspect_files", ("inspect", "read", "file", "確認", "読む")),
    ("run_tests", ("pytest", "test", "tests", "spec", "検証")),
    ("write_markdown", ("markdown", ".md", "readme", "draft", "記事", "日報")),
    ("edit_config", (".env", "config", "設定", "yaml", "json")),
    ("implement_feature", ("implement", "add", "build", "create", "実装")),
    ("debug_failure", ("debug", "fix", "error", "bug", "failure", "修正")),
    ("prepare_report", ("report", "daily", "summary", "報告", "レポート")),
]

ARTIFACT_HINT_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("review", ("review", "findings", "pr", "指摘", "レビュー")),
    ("markdown", ("markdown", ".md", "readme", "記事", "日報")),
    ("report", ("report", "daily", "summary", "レポート", "報告")),
    ("config", ("config", ".env", "yaml", "json", "設定")),
    ("code", ("python", "ts", "tsx", "js", "実装", "コード")),
]

REPEATED_RULE_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("findings-first", ("findings", "severity", "指摘", "severity順")),
    ("file-line-refs", ("line", "file", "行番号", "ファイル名")),
    ("concise-updates", ("concise", "short", "簡潔", "1-2 sentence")),
    ("tests-before-close", ("test", "pytest", "verification", "検証")),
]

URL_PATTERN = re.compile(r"https?://[^\s<>\"]+")
PATH_PATTERN = re.compile(r"(/[^ \n\t`\"']+)")
WORD_PATTERN = re.compile(r"[A-Za-z0-9_./+-]+|[一-龥ぁ-んァ-ン]+")


def sanitize_url_domain(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if not parsed.scheme or not parsed.netloc:
        return raw_url
    return f"{parsed.scheme}://{parsed.netloc}"


def mask_paths(text: str, workspace: str | None) -> str:
    masked = text
    if workspace:
        normalized = str(Path(workspace).expanduser())
        masked = masked.replace(normalized, "[WORKSPACE]")
    masked = PATH_PATTERN.sub(_replace_path_token, masked)
    return masked


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
    lowered = value.lower()
    return {token for token in WORD_PATTERN.findall(lowered) if len(token) > 1}


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


def infer_task_shapes(texts: list[str], tools: list[str]) -> list[str]:
    corpus = " ".join(texts + tools).lower()
    shapes: list[str] = []
    for label, patterns in TASK_SHAPE_PATTERNS:
        if any(pattern.lower() in corpus for pattern in patterns):
            shapes.append(label)
        if len(shapes) >= 3:
            break
    return shapes


def infer_artifact_hints(texts: list[str], tools: list[str]) -> list[str]:
    corpus = " ".join(texts + tools).lower()
    hints: list[str] = []
    for label, patterns in ARTIFACT_HINT_PATTERNS:
        if any(pattern.lower() in corpus for pattern in patterns):
            hints.append(label)
    return hints[:3]


def infer_repeated_rules(texts: list[str], workspace: str | None) -> list[dict[str, str]]:
    rules: list[dict[str, str]] = []
    seen: set[str] = set()
    for text in texts:
        lowered = text.lower()
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
    current = ensure_datetime(value)
    if current is None:
        return 0
    return int(current.timestamp())


def compare_iso_timestamps(value: str | None) -> str:
    return value or ""


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
    intent = str(packet.get("primary_intent") or "").strip()
    if intent:
        return summarize_text(intent, 64)
    shapes = packet.get("task_shape") or []
    if shapes:
        return str(shapes[0]).replace("_", " ")
    return "Unnamed candidate"


def candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, int, str]:
    return (
        float(candidate.get("score", 0.0)),
        int(candidate.get("support", {}).get("total_packets", 0)),
        str(candidate.get("label", "")),
    )


def packet_sort_key(packet: dict[str, Any]) -> tuple[str, str]:
    return (compare_iso_timestamps(packet.get("timestamp")), str(packet.get("packet_id", "")))


def stable_block_key(packet: dict[str, Any]) -> str:
    top_tool = str(packet.get("top_tool") or "none")
    task_shapes = packet.get("task_shape") or []
    first_shape = str(task_shapes[0]) if task_shapes else "none"
    if top_tool != "none":
        return f"tool:{top_tool}"
    if first_shape != "none":
        return f"task:{first_shape}"
    return "misc"


def stable_block_keys(packet: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    top_tool = str(packet.get("top_tool") or "none")
    task_shapes = packet.get("task_shape") or []
    first_shape = str(task_shapes[0]) if task_shapes else "none"
    if top_tool != "none":
        keys.append(f"tool:{top_tool}")
    if first_shape != "none":
        keys.append(f"task:{first_shape}")
    if not keys:
        keys.append("misc")
    return keys


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
