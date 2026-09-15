#!/usr/bin/env python3
"""Resolve a Claude Code or Codex session identifier without mutation.

The resolver returns structured metadata and launch arguments. It never starts,
resumes, forks, or modifies a session.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


MAX_INPUT_BYTES = 512 * 1024 * 1024
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
class ResolveError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _default_home(env_name: str, suffix: str) -> Path:
    value = os.environ.get(env_name)
    return Path(value).expanduser() if value else Path.home() / suffix


def _regular_file(path: Path) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_size <= MAX_INPUT_BYTES


def _json_records(path: Path) -> Iterable[dict[str, Any]]:
    if not _regular_file(path):
        raise ResolveError("session_record_unreadable")
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                if not text.startswith("{"):
                    marker = text.find(": {")
                    if marker < 0:
                        continue
                    text = text[marker + 2 :]
                try:
                    value = json.loads(text)
                except (json.JSONDecodeError, UnicodeError):
                    # A live event log may end with one partially written line.
                    continue
                if isinstance(value, dict):
                    yield value
    except (OSError, UnicodeError) as exc:
        raise ResolveError("session_record_unreadable") from exc


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _launch_argv(provider: str, native_id: str, cwd: str | None) -> list[str]:
    if provider == "claude":
        return ["claude", "--resume", native_id, "--fork-session"]
    argv = ["codex", "fork"]
    if cwd:
        argv.extend(["-C", cwd])
    argv.append(native_id)
    return argv


def _native_store_path(provider: str, native_id: str, root: Path) -> Path | None:
    if provider == "claude":
        base = root / "projects"
        matches = [
            path
            for path in base.glob(f"**/{native_id}.jsonl")
            if _regular_file(path)
        ]
    else:
        base = root / "sessions"
        matches = [
            path
            for path in base.glob("**/*.jsonl")
            if path.name.endswith(f"-{native_id}.jsonl") and _regular_file(path)
        ]
    if len(matches) > 1:
        raise ResolveError("ambiguous_native_session")
    return matches[0] if matches else None


def _native_metadata(
    provider: str, path: Path
) -> tuple[str | None, str | None, dict[str, Any]]:
    cwd: str | None = None
    model: str | None = None
    boundary = {"status": "unknown", "turn_id": None, "completed_at": None}
    for record in _json_records(path):
        if provider == "codex":
            if record.get("type") == "session_meta":
                cwd = cwd or _text(_nested(record, "payload", "cwd"))
            if record.get("type") == "turn_context":
                cwd = cwd or _text(_nested(record, "payload", "cwd"))
                model = model or _text(_nested(record, "payload", "model"))
            event_type = (
                _text(_nested(record, "payload", "type"))
                if record.get("type") == "event_msg"
                else None
            )
            if event_type == "task_started":
                boundary = {
                    "status": "active",
                    "turn_id": _text(_nested(record, "payload", "turn_id")),
                    "completed_at": None,
                }
            elif event_type in {"task_complete", "task_completed"}:
                boundary = {
                    "status": "completed",
                    "turn_id": _text(_nested(record, "payload", "turn_id")),
                    "completed_at": _text(record.get("timestamp")),
                }
            elif event_type in {"task_failed", "task_cancelled"}:
                boundary = {
                    "status": "failed" if event_type == "task_failed" else "cancelled",
                    "turn_id": _text(_nested(record, "payload", "turn_id")),
                    "completed_at": _text(record.get("timestamp")),
                }
        else:
            cwd = cwd or _text(record.get("cwd"))
            model = (
                model
                or _text(_nested(record, "message", "model"))
                or _text(record.get("model"))
            )
            if record.get("type") == "user" and not record.get("isSidechain", False):
                boundary = {
                    "status": "active",
                    "turn_id": _text(record.get("promptId")) or _text(record.get("uuid")),
                    "completed_at": None,
                }
            elif record.get("type") == "result" and not record.get("isSidechain", False):
                boundary = {
                    "status": "completed" if not record.get("is_error", False) else "failed",
                    "turn_id": _text(record.get("uuid")),
                    "completed_at": _text(record.get("timestamp")),
                }
    return cwd, model, boundary


def _native_resolution(
    identifier: str, provider: str, root: Path
) -> dict[str, Any] | None:
    path = _native_store_path(provider, identifier, root)
    if path is None:
        return None
    cwd, model, boundary = _native_metadata(provider, path)
    return {
        "schema_version": 1,
        "input_id": identifier,
        "input_kind": provider,
        "provider": provider,
        "native_session_id": identifier,
        "native_session_available": True,
        "cwd": cwd,
        "model": model,
        "boundary": boundary,
        "source_record": str(path.resolve()),
        "native_record": str(path.resolve()),
        "launch_argv": _launch_argv(provider, identifier, cwd),
        "mutated": False,
    }


def resolve_session(
    identifier: str,
    *,
    kind: str = "auto",
    codex_home: Path | None = None,
    claude_home: Path | None = None,
) -> dict[str, Any]:
    if not IDENTIFIER_RE.fullmatch(identifier):
        raise ResolveError("invalid_session_id")
    codex_home = codex_home or _default_home("CODEX_HOME", ".codex")
    claude_home = claude_home or _default_home("CLAUDE_CONFIG_DIR", ".claude")

    candidates: list[dict[str, Any]] = []
    if kind in {"auto", "claude"}:
        claude = _native_resolution(identifier, "claude", claude_home)
        if claude:
            candidates.append(claude)
    if kind in {"auto", "codex"}:
        codex = _native_resolution(identifier, "codex", codex_home)
        if codex:
            candidates.append(codex)

    if not candidates:
        raise ResolveError("session_not_found")
    if len(candidates) > 1:
        raise ResolveError("ambiguous_session_id")
    return candidates[0]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Resolve a Claude Code or Codex session ID without changing it."
    )
    parser.add_argument("session_id")
    parser.add_argument(
        "--kind", choices=("auto", "claude", "codex"), default="auto"
    )
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--claude-home", type=Path)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = resolve_session(
            args.session_id,
            kind=args.kind,
            codex_home=args.codex_home,
            claude_home=args.claude_home,
        )
    except ResolveError as exc:
        print(
            json.dumps({"ok": False, "error": exc.code}, sort_keys=True),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {"ok": True, **result}, indent=2 if args.pretty else None, sort_keys=True
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
