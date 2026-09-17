#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import read_history


class ReadHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_reads_only_finalized_public_t3_messages_in_order(self) -> None:
        thread_id = "fc9817b3-f5b0-40ca-8c86-933844c4177e"
        path = self.root / "state.sqlite"
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                CREATE TABLE projection_thread_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    role TEXT,
                    text TEXT,
                    is_streaming INTEGER,
                    created_at TEXT
                )
                """
            )
            connection.executemany(
                "INSERT INTO projection_thread_messages VALUES (?, ?, ?, ?, ?, ?)",
                [
                    ("message-3", thread_id, "assistant", "second", 0, "2026-09-17T01:02:00Z"),
                    ("message-2", thread_id, "reasoning", "private", 0, "2026-09-17T01:01:00Z"),
                    ("message-1", thread_id, "user", "first", 0, "2026-09-17T01:00:00Z"),
                    ("message-4", thread_id, "assistant", "partial", 1, "2026-09-17T01:03:00Z"),
                    ("message-5", "another-thread", "user", "unrelated", 0, "2026-09-17T00:59:00Z"),
                ],
            )

        source = {
            "input_kind": "t3",
            "provider": "grok",
            "t3_thread_id": thread_id,
            "source_record": str(path),
            "native_record": None,
        }

        self.assertEqual(
            list(read_history.messages(source)),
            [
                {"role": "user", "text": "first"},
                {"role": "assistant", "text": "second"},
            ],
        )

    def test_native_codex_history_remains_supported(self) -> None:
        path = self.root / "codex.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "native"}],
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        source = {
            "input_kind": "codex",
            "provider": "codex",
            "native_record": str(path),
        }

        self.assertEqual(
            list(read_history.messages(source)),
            [{"role": "assistant", "text": "native"}],
        )


if __name__ == "__main__":
    unittest.main()
