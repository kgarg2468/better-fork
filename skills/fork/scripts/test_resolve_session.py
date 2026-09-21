#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import resolve_session


class ResolveSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.codex = self.root / "codex"
        self.claude = self.root / "claude"
        self.t3 = self.root / "t3"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def resolve(self, value: str, kind: str = "auto") -> dict[str, object]:
        return resolve_session.resolve_session(
            value,
            kind=kind,
            codex_home=self.codex,
            claude_home=self.claude,
            t3_home=self.t3,
        )

    def write_jsonl(self, path: Path, records: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def write_t3_state(self, thread_id: str) -> Path:
        path = self.t3 / "userdata" / "state.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.executescript(
                """
                CREATE TABLE projection_projects (
                    project_id TEXT PRIMARY KEY,
                    workspace_root TEXT
                );
                CREATE TABLE projection_threads (
                    thread_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    worktree_path TEXT,
                    latest_turn_id TEXT,
                    model_selection_json TEXT,
                    deleted_at TEXT
                );
                CREATE TABLE projection_thread_sessions (
                    thread_id TEXT PRIMARY KEY,
                    status TEXT,
                    provider_name TEXT,
                    provider_instance_id TEXT
                );
                CREATE TABLE projection_turns (
                    row_id INTEGER PRIMARY KEY,
                    thread_id TEXT,
                    turn_id TEXT,
                    state TEXT,
                    requested_at TEXT,
                    completed_at TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO projection_projects VALUES (?, ?)",
                ("project-1", "/repo"),
            )
            connection.execute(
                "INSERT INTO projection_threads VALUES (?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    "project-1",
                    None,
                    "turn-1",
                    json.dumps({"instanceId": "grok", "model": "grok-4.6"}),
                    None,
                ),
            )
            connection.execute(
                "INSERT INTO projection_thread_sessions VALUES (?, ?, ?, ?)",
                (thread_id, "stopped", "grok", "grok"),
            )
            connection.execute(
                "INSERT INTO projection_turns VALUES (?, ?, ?, ?, ?, ?)",
                (
                    1,
                    thread_id,
                    "turn-1",
                    "completed",
                    "2026-09-17T01:00:00Z",
                    "2026-09-17T01:01:00Z",
                ),
            )
        return path

    def test_resolves_t3_grok_thread_for_attachment(self) -> None:
        thread_id = "fc9817b3-f5b0-40ca-8c86-933844c4177e"
        state_path = self.write_t3_state(thread_id)

        result = resolve_session.resolve_session(
            thread_id,
            codex_home=self.codex,
            claude_home=self.claude,
            t3_home=self.t3,
        )

        self.assertEqual(result["input_kind"], "t3")
        self.assertEqual(result["provider"], "grok")
        self.assertEqual(result["t3_thread_id"], thread_id)
        self.assertEqual(result["cwd"], "/repo")
        self.assertEqual(result["model"], "grok-4.6")
        self.assertEqual(
            result["boundary"],
            {
                "row_id": 1,
                "status": "completed",
                "turn_id": "turn-1",
                "completed_at": "2026-09-17T01:01:00Z",
            },
        )
        self.assertTrue(result["attachment_available"])
        self.assertFalse(result["native_session_available"])
        self.assertIsNone(result["native_session_id"])
        self.assertIsNone(result["native_record"])
        self.assertIsNone(result["launch_argv"])
        self.assertEqual(result["source_record"], str(state_path.resolve()))

    def test_rejects_malformed_t3_state(self) -> None:
        path = self.t3 / "userdata" / "state.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not a sqlite database", encoding="utf-8")

        with self.assertRaisesRegex(resolve_session.ResolveError, "t3_state_unreadable"):
            resolve_session.resolve_session(
                "fc9817b3-f5b0-40ca-8c86-933844c4177e",
                kind="t3",
                t3_home=self.t3,
            )

    def test_rejects_symlinked_t3_state(self) -> None:
        path = self.t3 / "userdata" / "state.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        target = self.root / "other-state.sqlite"
        target.write_bytes(b"")
        path.symlink_to(target)

        with self.assertRaisesRegex(resolve_session.ResolveError, "t3_state_unreadable"):
            resolve_session.resolve_session(
                "fc9817b3-f5b0-40ca-8c86-933844c4177e",
                kind="t3",
                t3_home=self.t3,
            )

    def test_resolves_native_claude_id(self) -> None:
        session_id = "abb98430-6ee6-4ab4-ae34-292fd9e69980"
        self.write_jsonl(
            self.claude / "projects" / "workspace" / f"{session_id}.jsonl",
            [
                {
                    "type": "user",
                    "uuid": "turn-1",
                    "cwd": "/repo",
                    "sessionId": session_id,
                },
                {
                    "type": "assistant",
                    "message": {"model": "claude-fable-5"},
                    "cwd": "/repo",
                    "sessionId": session_id,
                },
                {
                    "type": "result",
                    "uuid": "result-1",
                    "timestamp": "2026-01-01T00:00:00Z",
                },
            ],
        )
        result = self.resolve(session_id)
        self.assertEqual(result["input_kind"], "claude")
        self.assertEqual(result["provider"], "claude")
        self.assertEqual(result["cwd"], "/repo")
        self.assertEqual(result["model"], "claude-fable-5")
        self.assertEqual(result["boundary"]["status"], "completed")

    def test_resolves_native_codex_id(self) -> None:
        session_id = "01a07311-ede5-7403-9724-d6572f775573"
        self.write_jsonl(
            self.codex
            / "sessions"
            / "2026"
            / "09"
            / "05"
            / f"rollout-date-{session_id}.jsonl",
            [
                {
                    "type": "session_meta",
                    "payload": {"id": session_id, "cwd": "/repo"},
                },
                {
                    "type": "turn_context",
                    "payload": {"cwd": "/repo", "model": "gpt-test"},
                },
                {
                    "type": "event_msg",
                    "payload": {"type": "task_started", "turn_id": "turn-1"},
                },
                {
                    "timestamp": "done",
                    "type": "event_msg",
                    "payload": {"type": "task_complete", "turn_id": "turn-1"},
                },
            ],
        )
        result = self.resolve(session_id)
        self.assertEqual(result["input_kind"], "codex")
        self.assertEqual(result["native_session_id"], session_id)
        self.assertEqual(
            result["launch_argv"],
            ["codex", "fork", "-C", "/repo", session_id],
        )
        self.assertEqual(result["boundary"]["status"], "completed")

    def test_unreadable_t3_state_does_not_block_native_codex_resolution(self) -> None:
        session_id = "01a07311-ede5-7403-9724-d6572f775573"
        self.write_jsonl(
            self.codex
            / "sessions"
            / "2026"
            / "09"
            / "05"
            / f"rollout-date-{session_id}.jsonl",
            [
                {
                    "type": "session_meta",
                    "payload": {"id": session_id, "cwd": "/repo"},
                }
            ],
        )
        state_path = self.t3 / "userdata" / "state.sqlite"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text("not a sqlite database", encoding="utf-8")

        result = self.resolve(session_id)

        self.assertEqual(result["input_kind"], "codex")
        self.assertEqual(result["native_session_id"], session_id)

    def test_unknown_id_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            resolve_session.ResolveError, "session_not_found"
        ):
            self.resolve("00000000-0000-0000-0000-000000000000")


if __name__ == "__main__":
    unittest.main()
