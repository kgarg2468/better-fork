#!/usr/bin/env python3
from __future__ import annotations

import json
import contextlib
import io
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
            connection.executescript(
                """
                CREATE TABLE projection_thread_messages (
                    message_id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    turn_id TEXT,
                    role TEXT,
                    text TEXT,
                    is_streaming INTEGER,
                    created_at TEXT
                );
                CREATE TABLE projection_turns (
                    row_id INTEGER PRIMARY KEY,
                    thread_id TEXT,
                    turn_id TEXT,
                    pending_message_id TEXT,
                    assistant_message_id TEXT,
                    state TEXT,
                    completed_at TEXT
                );
                """
            )
            connection.executemany(
                "INSERT INTO projection_turns VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        1,
                        thread_id,
                        "turn-completed",
                        "message-1",
                        "message-3",
                        "completed",
                        "2026-09-17T01:03:00Z",
                    ),
                    (
                        2,
                        thread_id,
                        "turn-active",
                        "message-6",
                        "message-7",
                        "active",
                        None,
                    ),
                    (
                        3,
                        thread_id,
                        "turn-after-boundary",
                        "message-8",
                        "message-9",
                        "completed",
                        "2026-09-17T01:07:00Z",
                    ),
                ],
            )
            connection.executemany(
                "INSERT INTO projection_thread_messages VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    ("message-3", thread_id, "turn-completed", "assistant", "second", 0, "2026-09-17T01:02:00Z"),
                    ("message-2", thread_id, "turn-completed", "reasoning", "private", 0, "2026-09-17T01:01:00Z"),
                    ("message-1", thread_id, None, "user", "first", 0, "2026-09-17T01:00:00Z"),
                    ("message-4", thread_id, "turn-completed", "assistant", "partial", 1, "2026-09-17T01:03:00Z"),
                    ("message-5", "another-thread", None, "user", "unrelated", 0, "2026-09-17T00:59:00Z"),
                    ("message-6", thread_id, None, "user", "unfinished prompt", 0, "2026-09-17T01:04:00Z"),
                    ("message-7", thread_id, "turn-active", "assistant", "unfinished answer", 0, "2026-09-17T01:05:00Z"),
                    ("message-8", thread_id, None, "user", "later prompt", 0, "2026-09-17T01:06:00Z"),
                    ("message-9", thread_id, "turn-after-boundary", "assistant", "later answer", 0, "2026-09-17T01:06:30Z"),
                ],
            )

        source = {
            "input_kind": "t3",
            "provider": "grok",
            "t3_thread_id": thread_id,
            "source_record": str(path),
            "native_record": None,
            "boundary": {
                "status": "completed",
                "turn_id": "turn-completed",
                "completed_at": "2026-09-17T01:03:00Z",
            },
        }

        self.assertEqual(
            list(read_history.messages(source)),
            [
                {"role": "user", "text": "first"},
                {"role": "assistant", "text": "second"},
            ],
        )

        # A running head still permits the preceding completed conversation.
        source['boundary'] = {'status': 'running', 'turn_id': 'turn-active'}
        self.assertEqual(list(read_history.messages(source)), [
            {'role': 'user', 'text': 'first'},
            {'role': 'assistant', 'text': 'second'},
        ])
        self.assertEqual(source['attachment_boundary']['turn_id'], 'turn-completed')

        # Reproduce a queued head without a provider turn ID.
        with sqlite3.connect(path) as connection:
            connection.execute(
                'INSERT INTO projection_turns VALUES (?, ?, ?, ?, ?, ?, ?)',
                (4, thread_id, None, 'queued', None, 'pending', None),
            )
        source['boundary'] = {'status': 'pending', 'turn_id': None}
        recovered = list(read_history.messages(source))
        self.assertEqual([r['text'] for r in recovered],
                         ['first', 'second', 'later prompt', 'later answer'])
        self.assertEqual(source['attachment_boundary']['turn_id'], 'turn-after-boundary')

        # The CLI supplies a replayable, pinned command for subsequent pages.
        stdout = io.StringIO()
        with patch.object(read_history, 'resolve_session', return_value=source), \
             patch.object(sys, 'argv', ['read_history.py', thread_id, '--limit', '1']), \
             contextlib.redirect_stdout(stdout):
            self.assertIsNone(read_history.main())
        first = json.loads(stdout.getvalue())
        self.assertEqual(first['next_argv'][-2:], ['--through-turn', 'turn-after-boundary'])
        stdout = io.StringIO()
        with patch.object(read_history, 'resolve_session', return_value=source), \
             patch.object(sys, 'argv', first['next_argv'][1:]), \
             contextlib.redirect_stdout(stdout):
            read_history.main()
        self.assertEqual(json.loads(stdout.getvalue())['records'],
                         [{'role': 'assistant', 'text': 'second'}])
        stderr = io.StringIO()
        with patch.object(read_history, 'resolve_session', return_value=source), \
             patch.object(sys, 'argv', ['read_history.py', thread_id, '--offset', '1']), \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(read_history.main(), 2)
        self.assertEqual(json.loads(stderr.getvalue())['error'],
                         't3_pagination_requires_through_turn')

        # Pages explicitly pinned to the first completed turn ignore later work.
        self.assertEqual(list(read_history.messages(source, 'turn-completed')), [
            {'role': 'user', 'text': 'first'},
            {'role': 'assistant', 'text': 'second'},
        ])
        with self.assertRaisesRegex(ValueError, 't3_attachment_boundary_unavailable'):
            list(read_history.messages(source, 'turn-active'))

        # A resolver-captured queued row cannot include subsequently appended turns.
        source['boundary'] = {'status': 'pending', 'turn_id': None, 'row_id': 2}
        self.assertEqual([r['text'] for r in read_history.messages(source)], ['first', 'second'])

        # Do not substitute another boundary when an explicit ID is missing.
        source['boundary'] = {'status': 'completed', 'turn_id': 'missing'}
        with self.assertRaisesRegex(ValueError, 't3_history_unavailable'):
            list(read_history.messages(source))

        with sqlite3.connect(path) as connection:
            connection.execute("DELETE FROM projection_turns WHERE state = 'completed'")
        source['boundary'] = {'status': 'pending', 'turn_id': None}
        with self.assertRaisesRegex(ValueError, 't3_no_completed_history'):
            list(read_history.messages(source))

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
