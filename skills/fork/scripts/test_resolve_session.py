#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import resolve_session


class ResolveSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.t3 = self.root / "t3"
        self.codex = self.root / "codex"
        self.claude = self.root / "claude"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def resolve(self, value: str, kind: str = "auto") -> dict[str, object]:
        return resolve_session.resolve_session(
            value,
            kind=kind,
            t3_home=self.t3,
            codex_home=self.codex,
            claude_home=self.claude,
        )

    def write_jsonl(self, path: Path, records: list[dict[str, object]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
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

    def test_resolves_t3_id_to_claude(self) -> None:
        t3_id = "1b514968-c2bf-4eed-8050-e4b2c9b8aa81"
        native_id = "abb98430-6ee6-4ab4-ae34-292fd9e69980"
        self.write_jsonl(
            self.claude / "projects" / "workspace" / f"{native_id}.jsonl",
            [{"type": "user", "cwd": "/repo", "sessionId": native_id}],
        )
        event_path = (
            self.t3
            / "userdata"
            / "logs"
            / "provider"
            / f"events.{t3_id}.log"
        )
        self.write_jsonl(
            event_path,
            [
                {
                    "type": "session.configured",
                    "provider": "claudeAgent",
                    "threadId": t3_id,
                    "payload": {
                        "config": {"cwd": "/repo", "model": "claude-fable-5"}
                    },
                },
                {
                    "type": "thread.started",
                    "provider": "claudeAgent",
                    "threadId": t3_id,
                    "payload": {"providerThreadId": native_id},
                },
                {
                    "type": "turn.completed",
                    "provider": "claudeAgent",
                    "threadId": t3_id,
                    "turnId": "turn-1",
                    "createdAt": "done",
                },
            ],
        )
        result = self.resolve(t3_id)
        self.assertEqual(result["input_kind"], "t3")
        self.assertEqual(result["provider"], "claude")
        self.assertEqual(result["native_session_id"], native_id)
        self.assertTrue(result["native_session_available"])
        self.assertEqual(
            result["launch_argv"],
            ["claude", "--resume", native_id, "--fork-session"],
        )

    def test_resolves_t3_id_to_codex_from_raw_payload(self) -> None:
        t3_id = "111cccd3-48a3-4c29-a19e-ef7876cca1c8"
        native_id = "01a07311-ede5-7403-9724-d6572f775573"
        self.write_jsonl(
            self.codex
            / "sessions"
            / "date"
            / f"rollout-date-{native_id}.jsonl",
            [{"type": "session_meta", "payload": {"id": native_id, "cwd": "/repo"}}],
        )
        event_path = (
            self.t3
            / "userdata"
            / "logs"
            / "provider"
            / f"events.{t3_id}.log"
        )
        self.write_jsonl(
            event_path,
            [
                {
                    "type": "item.completed",
                    "provider": "codex",
                    "threadId": t3_id,
                    "raw": {"payload": {"threadId": native_id}},
                },
                {
                    "type": "turn.completed",
                    "provider": "codex",
                    "threadId": t3_id,
                    "turnId": "turn-1",
                    "createdAt": "done",
                    "raw": {"payload": {"threadId": native_id}},
                },
            ],
        )
        result = self.resolve(t3_id)
        self.assertEqual(result["provider"], "codex")
        self.assertEqual(result["native_session_id"], native_id)
        self.assertEqual(result["boundary"]["status"], "completed")

    def test_unknown_id_fails_closed(self) -> None:
        with self.assertRaisesRegex(
            resolve_session.ResolveError, "session_not_found"
        ):
            self.resolve("00000000-0000-0000-0000-000000000000")


if __name__ == "__main__":
    unittest.main()
