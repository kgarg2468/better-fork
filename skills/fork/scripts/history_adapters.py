"""Portable, public history projections. Never edit provider stores."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from fork_context import ForkContextError, MAX_HISTORY_BYTES, _canonical, _parse_json, _reject_secrets
from resolve_session import MAX_INPUT_BYTES


def load_rows(path, *, metadata_only=False):
    """Stream a fixed byte range. Native planning does not use the export budget."""
    rows = []
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(descriptor, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INPUT_BYTES:
            raise ValueError("native_input_too_large_or_not_regular")
        remaining = info.st_size
        while remaining:
            raw = handle.readline(remaining)
            if not raw:
                raise ValueError('native_history_changed_during_read')
            remaining -= len(raw)
            if not raw.strip():
                continue
            try:
                row = _parse_json(raw.decode('utf-8'))
            except (ForkContextError, UnicodeError):
                if remaining == 0 and not raw.endswith(b'\n'):
                    break
                raise ValueError("malformed_native_history") from None
            if not isinstance(row, dict):
                raise ValueError("malformed_native_history")
            for key in ("message", "payload"):
                if key in row and not isinstance(row[key], dict):
                    raise ValueError("malformed_native_history")
            if metadata_only:
                if row.get('type') == 'response_item':
                    row['payload'] = {'type': row.get('payload', {}).get('type')}
                if 'message' in row:
                    message = row['message']
                    blocks = message.get('content')
                    row['message'] = {'stop_reason': message.get('stop_reason'),
                                      'content': '<text>' if isinstance(blocks, str) else
                                      [{'type': b.get('type')} for b in (blocks or []) if isinstance(b, dict)]}
            else:
                row = strip_binary(row)
            rows.append(row)
    return rows


def strip_binary(row):
    def blocks(content):
        if not isinstance(content, list):
            return content
        output = []
        for block in content:
            if not isinstance(block, dict):
                output.append(block)
                continue
            kind = block.get('type')
            if kind in {'image', 'input_image', 'image_url', 'document', 'input_file'}:
                source = block.get('source')
                ref = {key: block[key] for key in ('type', 'media_type', 'filename', 'file_id', 'title') if isinstance(block.get(key), str)}
                if isinstance(source, dict) and isinstance(source.get('media_type'), str):
                    ref['media_type'] = source['media_type']
                output.append(ref)
            elif kind == 'tool_result':
                output.append({**block, 'content': blocks(block.get('content'))})
            else:
                # A tool's arguments can contain application data with a `type`
                # field. Only provider content blocks describe binary attachments.
                output.append(block)
        return output
    if 'message' in row and 'content' in row['message']:
        row['message']['content'] = blocks(row['message']['content'])
    payload = row.get('payload', {})
    if row.get('type') == 'response_item':
        if payload.get('type') == 'message':
            payload['content'] = blocks(payload.get('content'))
        elif payload.get('type') in {'function_call_output', 'custom_tool_call_output'}:
            payload['output'] = blocks(payload.get('output'))
    return row


def codex_boundary(rows, through_turn=None):
    completed = []
    active = None
    for index, row in enumerate(rows):
        if row.get("type") != "event_msg":
            continue
        event = row.get("payload", {})
        if event.get('type') in {'thread_rolled_back', 'thread_reverted'}:
            # Do not resurrect discarded turns from append-only legacy logs.
            # Reconstructing these needs a provider-normalized history export.
            raise ValueError('native_history_rewrite_requires_provider_export')
        if event.get("type") == "task_started":
            active = event.get("turn_id")
        elif event.get("type") in {"task_complete", "task_completed"}:
            turn = event.get("turn_id") or active
            if turn and turn == active:
                completed.append((turn, index))
            active = None
        elif event.get("type") in {"task_failed", "task_cancelled", "turn_aborted"}:
            active = None
    matches = [item for item in completed if through_turn is None or item[0] == through_turn]
    if not matches:
        raise ValueError("completed_boundary_unavailable")
    return matches[-1]


def claude_chain(rows):
    main = [r for r in rows if not r.get("isSidechain")]
    nodes = {r["uuid"]: r for r in main if isinstance(r.get("uuid"), str)}
    messages = [r for r in main if r.get("type") in {"user", "assistant"} and r.get("uuid")]
    if not messages:
        raise ValueError("completed_boundary_unavailable")
    compacted = any(r.get('subtype') == 'compact_boundary' or r.get('logicalParentUuid') or r.get('isCompactSummary') for r in main)
    # Old linear exports may not carry ancestry. Do not invent a branch in those.
    if not any("parentUuid" in r for r in messages):
        return main, compacted
    current = messages[-1]
    chain = []
    seen = set()
    missing = compacted
    while current:
        uuid = current.get("uuid")
        if uuid in seen:
            raise ValueError("invalid_message_ancestry")
        seen.add(uuid)
        chain.append(current)
        parent = current.get("parentUuid")
        if not parent:
            break
        current = nodes.get(parent)
        if current is None:
            missing = True
    chain.reverse()
    # Completion markers can follow the last message and aren't message ancestors.
    markers = {}
    for r in main:
        if r.get("type") == "result" or (r.get("type") == "system" and r.get("subtype") == "turn_duration"):
            if r.get("parentUuid") in seen and r.get('uuid') not in seen:
                markers.setdefault(r['parentUuid'], []).append(r)
    chain = [item for r in chain for item in [r, *markers.get(r.get('uuid'), [])]]
    return chain, missing


def claude_boundary(rows, through_turn=None):
    completed = []
    last_assistant = None
    for index, row in enumerate(rows):
        if row.get("type") == "assistant":
            last_assistant = (row.get("uuid"), index)
            if row.get("message", {}).get("stop_reason") in {"end_turn", "stop_sequence"} and last_assistant[0]:
                completed.append(last_assistant)
        elif ((row.get("type") == "system" and row.get("subtype") == "turn_duration") or
              (row.get("type") == "result" and not row.get("is_error"))):
            if last_assistant and last_assistant[0]:
                completed.append(last_assistant)
        elif row.get("type") == "user":
            blocks = row.get("message", {}).get("content") or []
            if isinstance(blocks, str) or any(b.get("type") != "tool_result" for b in blocks if isinstance(b, dict)):
                last_assistant = None
    matches = [item for item in completed if through_turn is None or item[0] == through_turn]
    if not matches:
        raise ValueError("completed_boundary_unavailable")
    return matches[-1]


class Projection:
    def __init__(self, provider):
        self.provider = provider
        self.records = []
        self.calls = {}
        self.withheld = []
        self.excluded_turns = 0
        self.omissions = {"provider_instructions", "hidden_reasoning", "external_process_state"}

    def add(self, identifier, role, text):
        if not isinstance(text, str) or not text:
            return
        self.records.append({"id": f"{self.provider}:{identifier}", "role": role, "text": text})

    def tool_call(self, identifier, call_id, name, arguments):
        if not isinstance(call_id, str) or not call_id:
            self.omissions.add("unidentified_tool_call")
            return
        if call_id in self.calls:
            raise ValueError("duplicate_tool_call_id")
        item = {"kind": "tool_execution", "call_id": call_id, "name": name, "arguments": arguments, "result_available": False}
        self.add(identifier, "tool", json.dumps(item, ensure_ascii=False))
        self.calls[call_id] = (self.records[-1], item)

    def tool_result(self, identifier, call_id, output, is_error=None):
        if isinstance(output, list):
            output = [b.get('text', '') if b.get('type') in {'text', 'input_text', 'output_text'} else self.reference(b)
                      for b in output if isinstance(b, dict)]
        if call_id in self.calls:
            record, item = self.calls[call_id]
            if item["result_available"]:
                raise ValueError("duplicate_tool_result")
            item.update(output=output, result_available=True, is_error=is_error)
            record["text"] = json.dumps(item, ensure_ascii=False)
        else:
            self.omissions.add("tool_call_missing_for_result")
            self.add(identifier, "tool", json.dumps({"kind": "tool_result", "call_id": call_id, "output": output, "is_error": is_error}, ensure_ascii=False))

    def content(self, identifier, role, content):
        if isinstance(content, str):
            self.add(identifier, role, content)
            return
        if not isinstance(content, list):
            self.omissions.add("unsupported_content")
            return
        for i, block in enumerate(content):
            if not isinstance(block, dict):
                self.omissions.add("unsupported_content")
                continue
            key = f"{identifier}:{i}"
            kind = block.get("type")
            if kind in {"text", "input_text", "output_text"}:
                self.add(key, role, block.get("text"))
            elif kind == "tool_use":
                self.tool_call(key, block.get("id"), block.get("name"), block.get("input"))
            elif kind == "tool_result":
                output = block.get("content", "")
                self.tool_result(key, block.get("tool_use_id"), output, block.get("is_error"))
            elif kind in {"image", "input_image", "image_url", "document", "input_file"}:
                self.add(key, role, json.dumps(self.reference(block), ensure_ascii=False))
            elif kind not in {"thinking", "redacted_thinking", "reasoning"}:
                self.omissions.add("unsupported_content")

    def reference(self, block):
        self.omissions.add("attachment_bytes")
        source = block.get("source", {})
        if not isinstance(source, dict):
            source = {}
        ref = {"kind": "attachment_reference", "type": block.get("type"), "available": False}
        for key in ("media_type", "filename", "file_id", "title"):
            value = block.get(key, source.get(key))
            if isinstance(value, str):
                ref[key] = value
        # Do not copy inline data or remote URLs (which may contain signed credentials).
        return ref

    def finish(self):
        if any(not item[1]["result_available"] for item in self.calls.values()):
            self.omissions.add("tool_result_unavailable")
        for record in self.records:
            try:
                _reject_secrets(record)
            except ForkContextError:
                if record['role'] != 'tool':
                    raise
                self.withheld.append(record['id'])
                record['text'] = '[Tool evidence withheld: secret-like content detected. Original content is not in this snapshot.]'
                self.omissions.add('secret_like_tool_record_withheld')
        if len(_canonical(self.records)) > MAX_HISTORY_BYTES:
            raise ValueError("portable_history_too_large")
        return self.records


def native_snapshot(source, through_turn=None):
    provider = source["provider"]
    rows = load_rows(source["native_record"])
    projection = Projection(provider)
    missing = False
    if provider == "claude":
        rows, missing = claude_chain(rows)
        boundary, end = claude_boundary(rows, through_turn)
        for i, row in enumerate(rows[:end + 1]):
            role = row.get("type")
            if role in {"user", "assistant"}:
                projection.content(row.get("uuid", str(i)), role, row.get("message", {}).get("content", []))
    elif provider == "codex":
        boundary, end = codex_boundary(rows, through_turn)
        # Only finalized turns belong in the public projection, not bootstrap prompts
        # or failed/interrupted requests interleaved before a later completed turn.
        pending = []
        active = None
        selected = []
        for i, row in enumerate(rows[:end + 1]):
            payload = row.get("payload", {})
            if row.get("type") == "event_msg":
                event = payload.get("type")
                if event == "task_started":
                    if active:
                        projection.excluded_turns += 1
                    pending, active = [], payload.get('turn_id')
                elif event in {"task_complete", "task_completed"}:
                    if active and (payload.get('turn_id') or active) == active:
                        selected.extend(pending)
                    else:
                        projection.excluded_turns += 1
                    pending, active = [], None
                elif event in {"task_failed", "task_cancelled", "turn_aborted"}:
                    projection.excluded_turns += 1
                    pending, active = [], None
            elif active and row.get("type") == "response_item":
                pending.append((i, payload))
            elif row.get("type") == "compacted":
                missing = True
        for i, item in selected:
            kind = item.get("type")
            if kind == "message" and item.get("role") in {"user", "assistant"}:
                projection.content(str(i), item["role"], item.get("content", []))
            elif kind in {"function_call", "custom_tool_call"}:
                projection.tool_call(str(i), item.get("call_id"), item.get("name"), item.get("arguments", item.get("input")))
            elif kind in {"function_call_output", "custom_tool_call_output"}:
                projection.tool_result(str(i), item.get("call_id"), item.get("output"))
            elif kind not in {"message", "reasoning"}:
                projection.omissions.add("unsupported_native_item")
    else:
        raise ValueError("unsupported_native_provider")
    if missing:
        projection.omissions.add("incomplete_or_compacted_ancestry")
    if projection.excluded_turns:
        projection.omissions.add('unfinished_turns_excluded')
    return make_snapshot(source, boundary, projection, excluded_later=end < len(rows) - 1, partial=missing)


def make_snapshot(source, boundary, projection, *, excluded_later=False, partial=False):
    records = projection.finish()
    if not records:
        raise ValueError("no_public_history")
    return {
        "history": {
            "schema_version": 1,
            "source": {"provider": source["provider"], "session_id": source["input_id"], "boundary": boundary, "coverage": "partial" if partial or projection.withheld or projection.excluded_turns else "complete"},
            "records": records,
        },
        "metadata": {
            "input_kind": source["input_kind"], "source_cwd": source.get("cwd"),
            "boundary_namespace": source["input_kind"], "excluded_later_content": excluded_later,
            "omissions": sorted(projection.omissions),
            "withheld_record_ids": projection.withheld, "excluded_unfinished_turns": projection.excluded_turns,
            "coverage_meaning": "public projection only, not native session completeness",
            "native_session_created": False, "host_thread_created": False,
        },
    }
