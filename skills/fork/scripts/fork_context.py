#!/usr/bin/env python3
"""Prepare and retrieve a private bundle from reviewed public history only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


MAX_HISTORY_BYTES = 50 * 1024 * 1024
MAX_TASK_BYTES = 5 * 1024 * 1024
MAX_SELECTION_BYTES = 1_000_000
ARTIFACTS = ("reviewed-history.json", "context.json", "next-task.txt")
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\b(?:sk|rk)-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}\b"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|client[_-]?secret)"
        r"\s*(?:=|:)\s*['\"]?[A-Za-z0-9._~+/@-]{12,}"
    ),
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:@]{1,128}:[^\s/@]{8,128}@", re.I),
)


class ForkContextError(Exception):
    """A value-free failure safe to report at the CLI."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ForkContextError("non_utf8_json_value") from exc


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ForkContextError("duplicate_json_key")
        result[key] = value
    return result


def _nonfinite(_value: str) -> None:
    raise ForkContextError("nonfinite_json_value")


def _parse_json(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except ForkContextError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise ForkContextError("invalid_json") from exc


def _read_regular(path: Path, maximum: int) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ForkContextError("input_open_failed") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ForkContextError("input_not_regular_file")
        if info.st_size > maximum:
            raise ForkContextError("input_too_large")
        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                chunk = os.read(fd, min(1024 * 1024, maximum + 1 - total))
            except OSError as exc:
                raise ForkContextError("input_read_failed") from exc
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum:
                raise ForkContextError("input_too_large")
        return b"".join(chunks)
    finally:
        os.close(fd)


def _decode_utf8(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ForkContextError("invalid_utf8") from exc


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _reject_secrets(value: Any) -> None:
    if any(pattern.search(text) for text in _strings(value) for pattern in SECRET_PATTERNS):
        raise ForkContextError("secret_like_value")


def _load_history(path: Path) -> tuple[dict[str, Any], bytes]:
    value = _parse_json(_decode_utf8(_read_regular(path, MAX_HISTORY_BYTES)))
    if not isinstance(value, dict) or set(value) != {"schema_version", "source", "records"}:
        raise ForkContextError("invalid_history_schema")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or not isinstance(value["source"], dict):
        raise ForkContextError("invalid_history_schema")
    source = value["source"]
    if set(source) != {"provider", "session_id", "boundary", "coverage"}:
        raise ForkContextError("invalid_source_schema")
    if not all(isinstance(source.get(key), str) and source[key] for key in ("provider", "session_id", "boundary")):
        raise ForkContextError("invalid_source_schema")
    if not isinstance(source.get("coverage"), str) or source["coverage"] not in {"complete", "partial"}:
        raise ForkContextError("invalid_source_coverage")
    if not isinstance(value["records"], list):
        raise ForkContextError("invalid_records")
    seen: set[str] = set()
    for record in value["records"]:
        if not isinstance(record, dict) or set(record) != {"id", "role", "text"}:
            raise ForkContextError("invalid_record_schema")
        if not isinstance(record["id"], str) or not record["id"]:
            raise ForkContextError("invalid_record_id")
        if record["id"] in seen:
            raise ForkContextError("duplicate_record_id")
        seen.add(record["id"])
        if not isinstance(record["role"], str) or record["role"] not in {"user", "assistant", "tool"}:
            raise ForkContextError("invalid_record_role")
        if not isinstance(record["text"], str):
            raise ForkContextError("invalid_record_text")
    _reject_secrets(value)
    canonical = _canonical(value) + b"\n"
    return value, canonical


def _selection_plan(
    raw: str | None, records: list[dict[str, str]]
) -> tuple[dict[str, Any] | None, str | None]:
    if raw is None:
        return None, None
    try:
        selection_size = len(raw.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ForkContextError("non_utf8_json_value") from exc
    if selection_size > MAX_SELECTION_BYTES:
        return None, "selection_too_large"
    try:
        value = _parse_json(raw)
    except ForkContextError:
        return None, "invalid_selection_json"
    required = {"retain_ids", "summary_ids", "summary_text"}
    if not isinstance(value, dict) or set(value) != required:
        return None, "invalid_selection_schema"
    retain = value["retain_ids"]
    summary = value["summary_ids"]
    if (
        not isinstance(retain, list)
        or not isinstance(summary, list)
        or not isinstance(value["summary_text"], str)
        or not all(isinstance(item, str) for item in retain + summary)
    ):
        return None, "invalid_selection_types"
    if len(set(retain)) != len(retain) or len(set(summary)) != len(summary):
        return None, "duplicate_selection_id"
    retain_set, summary_set = set(retain), set(summary)
    known = {record["id"] for record in records}
    users = {record["id"] for record in records if record["role"] == "user"}
    if retain_set & summary_set or not (retain_set | summary_set) <= known:
        return None, "invalid_selection_ids"
    if not users <= retain_set or users & summary_set:
        return None, "user_record_not_pinned"
    archive = [
        record["id"]
        for record in records
        if record["id"] not in retain_set and record["id"] not in summary_set
    ]
    if bool(summary) != bool(value["summary_text"].strip()):
        return None, "summary_linkage_mismatch"
    _reject_secrets(value["summary_text"])
    return {
        "retain_ids": retain_set,
        "summary_ids": summary_set,
        "summary_text": value["summary_text"],
        "archive_ids": archive,
    }, None


def _context(
    history: dict[str, Any], selection: str | None, budget: int | None
) -> dict[str, Any]:
    records = history["records"]
    plan, invalid_reason = _selection_plan(selection, records)
    if plan is None:
        selected = records
        summary_ids: list[str] = []
        summary_text = ""
        archive_ids: list[str] = []
        selected_chars = sum(len(record["text"]) for record in records)
        exceeded = budget is not None and selected_chars > budget
        fallback = invalid_reason is not None or exceeded
        mode = "fallback_full_context" if fallback else "full_context"
        reason = invalid_reason or ("budget_exceeded" if exceeded else None)
    else:
        selected = [record for record in records if record["id"] in plan["retain_ids"]]
        summary_ids = [record["id"] for record in records if record["id"] in plan["summary_ids"]]
        summary_text = plan["summary_text"]
        archive_ids = plan["archive_ids"]
        selected_chars = sum(len(record["text"]) for record in selected) + len(summary_text)
        exceeded = budget is not None and selected_chars > budget
        if exceeded:
            selected = records
            summary_ids, summary_text, archive_ids = [], "", []
            selected_chars = sum(len(record["text"]) for record in records)
            mode, reason = "fallback_full_context", "budget_exceeded"
        else:
            mode, reason = "selected_context", None
    return {
        "schema_version": 1,
        "kind": "fork_context",
        "source": dict(history["source"]),
        "mode": mode,
        "fallback_reason": reason,
        "budget_chars": budget,
        "budget_exceeded": exceeded,
        "budget_unit": "unicode_characters_in_retained_text_plus_summary_text",
        "context_characters": selected_chars,
        "retained_records": selected,
        "summary": {"source_ids": summary_ids, "text": summary_text},
        "archive_ids": archive_ids,
    }


def _safe_output(path: Path) -> None:
    if not path.is_absolute():
        raise ForkContextError("output_not_absolute")
    if os.path.lexists(path):
        raise ForkContextError("output_already_exists")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise ForkContextError("output_parent_invalid") from exc
    if parent != path.parent:
        raise ForkContextError("output_parent_symlink_or_noncanonical")


def _write_private(path: Path, value: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as target:
        os.fchmod(target.fileno(), 0o600)
        target.write(value)
        target.flush()
        os.fsync(target.fileno())


def prepare(
    history_path: Path,
    next_task_path: Path,
    output: Path,
    *,
    reviewed_public_history: bool,
    selection: str | None = None,
    budget_chars: int | None = None,
) -> dict[str, Any]:
    if not reviewed_public_history:
        raise ForkContextError("reviewed_public_history_declaration_required")
    if budget_chars is not None and budget_chars < 0:
        raise ForkContextError("invalid_budget_chars")
    history, history_bytes = _load_history(history_path)
    task = _decode_utf8(_read_regular(next_task_path, MAX_TASK_BYTES))
    if not task:
        raise ForkContextError("empty_next_task")
    _reject_secrets(task)
    context = _context(history, selection, budget_chars)
    context_bytes = _canonical(context) + b"\n"
    task_bytes = task.encode("utf-8")
    files = {
        "reviewed-history.json": history_bytes,
        "context.json": context_bytes,
        "next-task.txt": task_bytes,
    }
    manifest = {
        "schema_version": 1,
        "kind": "fork_context_bundle_manifest",
        "source": {
            **history["source"],
            "reviewed_public_history_declared": True,
            "reviewed_history_sha256": _sha256(history_bytes),
        },
        "context_mode": context["mode"],
        "budget_exceeded": context["budget_exceeded"],
        "native_textual_handoff_used": False,
        "native_session_launched": False,
        "model_or_api_called": False,
        "artifacts": {
            name: {"sha256": _sha256(value), "bytes": len(value)}
            for name, value in files.items()
        },
    }
    manifest_bytes = _canonical(manifest) + b"\n"
    manifest_digest = (_sha256(manifest_bytes) + "\n").encode("ascii")
    _safe_output(output)
    created = False
    written: list[Path] = []
    try:
        os.mkdir(output, 0o700)
        created = True
        os.chmod(output, 0o700)
        for name, value in files.items():
            target = output / name
            _write_private(target, value)
            written.append(target)
        _write_private(output / "manifest.json", manifest_bytes)
        written.append(output / "manifest.json")
        _write_private(output / "manifest.sha256", manifest_digest)
        written.append(output / "manifest.sha256")
    except Exception as exc:
        for target in reversed(written):
            try:
                target.unlink()
            except OSError:
                pass
        if created:
            try:
                output.rmdir()
            except OSError:
                pass
        if isinstance(exc, ForkContextError):
            raise
        raise ForkContextError("bundle_write_failed") from exc
    return {
        "schema_version": 1,
        "status": "prepared",
        "bundle_path_sha256": _sha256(str(output).encode()),
        "context_mode": context["mode"],
        "fallback_reason": context["fallback_reason"],
        "budget_exceeded": context["budget_exceeded"],
        "record_count": len(history["records"]),
        "coverage": history["source"]["coverage"],
        "manifest_sha256": manifest_digest.decode().strip(),
    }


def _bundle(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if not path.is_absolute():
        raise ForkContextError("invalid_bundle_path")
    try:
        if path.is_symlink() or not path.is_dir():
            raise ForkContextError("invalid_bundle_path")
        info = path.stat()
    except ForkContextError:
        raise
    except OSError as exc:
        raise ForkContextError("bundle_open_failed") from exc
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ForkContextError("bundle_not_private")
    manifest_raw = _read_regular(path / "manifest.json", MAX_HISTORY_BYTES)
    digest_raw = _decode_utf8(_read_regular(path / "manifest.sha256", 128)).strip()
    if not re.fullmatch(r"[0-9a-f]{64}", digest_raw) or _sha256(manifest_raw) != digest_raw:
        raise ForkContextError("manifest_hash_mismatch")
    manifest = _parse_json(_decode_utf8(manifest_raw))
    if not isinstance(manifest, dict) or manifest.get("kind") != "fork_context_bundle_manifest":
        raise ForkContextError("invalid_manifest")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACTS):
        raise ForkContextError("invalid_manifest_artifacts")
    loaded: dict[str, bytes] = {}
    for name in ARTIFACTS:
        metadata = artifacts[name]
        if not isinstance(metadata, dict) or set(metadata) != {"sha256", "bytes"}:
            raise ForkContextError("invalid_artifact_metadata")
        try:
            raw = _read_regular(path / name, MAX_HISTORY_BYTES)
        except ForkContextError as exc:
            raise ForkContextError("bundle_artifact_missing_or_invalid") from exc
        if len(raw) != metadata["bytes"] or _sha256(raw) != metadata["sha256"]:
            raise ForkContextError("artifact_hash_mismatch")
        loaded[name] = raw
    history = _parse_json(_decode_utf8(loaded["reviewed-history.json"]))
    validated, _canonical_history = _load_history(path / "reviewed-history.json")
    if history != validated:
        raise ForkContextError("reviewed_history_validation_mismatch")
    return manifest, history


def retrieve(bundle: Path, ids: Sequence[str]) -> dict[str, Any]:
    if not ids:
        raise ForkContextError("retrieve_id_required")
    if len(set(ids)) != len(ids):
        raise ForkContextError("duplicate_retrieve_id")
    manifest, history = _bundle(bundle)
    requested = set(ids)
    known = {record["id"] for record in history["records"]}
    if not requested <= known:
        raise ForkContextError("unknown_id")
    records = [record for record in history["records"] if record["id"] in requested]
    return {
        "schema_version": 1,
        "source": manifest["source"],
        "records": records,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare", help="build a new private context bundle")
    prepare_parser.add_argument("--history", required=True, type=Path)
    prepare_parser.add_argument("--next-task-file", required=True, type=Path)
    prepare_parser.add_argument("--output", required=True, type=Path)
    prepare_parser.add_argument(
        "--selection", type=Path, help="bounded UTF-8 JSON selection file"
    )
    prepare_parser.add_argument("--budget-chars", type=int)
    prepare_parser.add_argument(
        "--reviewed-public-history",
        action="store_true",
        required=True,
        help="declare that --history is reviewed public history, not raw native history",
    )
    retrieve_parser = commands.add_parser("retrieve", help="retrieve exact reviewed records")
    retrieve_parser.add_argument("--bundle", required=True, type=Path)
    retrieve_parser.add_argument("--id", action="append", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            selection = (
                _decode_utf8(_read_regular(args.selection, MAX_SELECTION_BYTES))
                if args.selection is not None
                else None
            )
            result = prepare(
                args.history,
                args.next_task_file,
                args.output,
                reviewed_public_history=args.reviewed_public_history,
                selection=selection,
                budget_chars=args.budget_chars,
            )
        else:
            result = retrieve(args.bundle, args.id)
    except ForkContextError as exc:
        print(json.dumps({"status": "failed_closed", "error": exc.code}, sort_keys=True))
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
