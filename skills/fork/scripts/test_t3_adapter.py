from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import read_history
import resolve_session


class T3AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = self.root / "t3" / "userdata" / "state.sqlite"
        self.database.parent.mkdir(parents=True)
        self.thread = "11111111-2222-4333-8444-555555555555"
        self.native = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        with sqlite3.connect(self.database) as c:
            c.executescript('''
            CREATE TABLE projection_projects(project_id TEXT, workspace_root TEXT);
            CREATE TABLE projection_threads(thread_id TEXT, project_id TEXT, worktree_path TEXT, latest_turn_id TEXT, model_selection_json TEXT, deleted_at TEXT);
            CREATE TABLE projection_thread_sessions(thread_id TEXT, provider_name TEXT, provider_instance_id TEXT, provider_session_id TEXT, provider_thread_id TEXT);
            CREATE TABLE projection_turns(row_id INTEGER, thread_id TEXT, turn_id TEXT, state TEXT, requested_at TEXT, completed_at TEXT, pending_message_id TEXT, assistant_message_id TEXT);
            CREATE TABLE projection_thread_messages(message_id TEXT, thread_id TEXT, turn_id TEXT, role TEXT, text TEXT, is_streaming INTEGER, created_at TEXT, attachments_json TEXT);
            CREATE TABLE projection_thread_activities(activity_id TEXT, thread_id TEXT, turn_id TEXT, kind TEXT, summary TEXT, payload_json TEXT, created_at TEXT);
            ''')
            c.execute("INSERT INTO projection_projects VALUES ('project', '/repo')")
            c.execute("INSERT INTO projection_threads VALUES (?, 'project', NULL, 't3-turn', ?, NULL)", (self.thread, json.dumps({"model": "gpt-test", "instanceId": "codex"})))
            c.execute("INSERT INTO projection_thread_sessions VALUES (?, 'codex', 'codex', ?, ?)", (self.thread, self.native, self.native))
            c.execute("INSERT INTO projection_turns VALUES (1, ?, 't3-turn', 'completed', '1', '4', 'u1', 'a1')", (self.thread,))
            c.execute("INSERT INTO projection_thread_messages VALUES ('u1', ?, 't3-turn', 'user', 'fix bug', 0, '1', ?)", (self.thread, json.dumps([{"name": "screen.png", "mimeType": "image/png", "data": "PRIVATE_BINARY"}])))
            c.execute("INSERT INTO projection_thread_messages VALUES ('a1', ?, 't3-turn', 'assistant', 'fixed', 0, '3', NULL)", (self.thread,))
            c.execute("INSERT INTO projection_thread_activities VALUES ('activity', ?, 't3-turn', 'tool.completed', 'Ran parser tests', ?, '2')", (self.thread, json.dumps({"private": "PRIVATE_PAYLOAD"})))
            c.execute("INSERT INTO projection_thread_activities VALUES ('reasoning', ?, 't3-turn', 'task.progress', 'PRIVATE_REASONING', '{}', '2')", (self.thread,))

    def tearDown(self):
        self.temp.cleanup()

    def resolve(self):
        return resolve_session.resolve_session(self.thread, t3_home=self.root / "t3", codex_home=self.root / "codex", claude_home=self.root / "claude")

    def test_native_mapping_must_exist_in_provider_store(self):
        self.assertFalse(self.resolve()["native_session_available"])
        folder = self.root / "codex" / "sessions"
        folder.mkdir(parents=True)
        path = folder / ("rollout-" + self.native + ".jsonl")
        path.write_text(json.dumps({"type": "session_meta", "payload": {"id": self.native, "cwd": "/repo"}}) + "\n")
        resolved = self.resolve()
        self.assertTrue(resolved["native_session_available"], "T3 mapping is not connected to native adapter")
        self.assertEqual(resolved["native_source"]["native_session_id"], self.native)
        self.assertEqual(resolved["input_kind"], "t3")
        self.assertEqual(resolved["boundary"]["turn_id"], "t3-turn")

    def test_public_t3_activity_and_attachment_metadata_without_private_payload(self):
        result = read_history.snapshot(self.resolve())
        text = json.dumps(result)
        self.assertIn("Ran parser tests", text)
        self.assertIn("screen.png", text)
        self.assertNotIn("PRIVATE_BINARY", text)
        self.assertNotIn("PRIVATE_PAYLOAD", text)
        self.assertNotIn("PRIVATE_REASONING", text)
        self.assertTrue(any(r["role"] == "tool" for r in result["history"]["records"]))

    def test_broken_optional_native_mapping_does_not_block_attachment(self):
        for suffix in ('a', 'b'):
            folder = self.root / 'codex' / 'sessions' / suffix
            folder.mkdir(parents=True)
            (folder / ('rollout-' + self.native + '.jsonl')).write_text('{}\n')
        resolved = self.resolve()
        self.assertFalse(resolved['native_session_available'])
        self.assertIn('native_mapping_note', resolved)
        self.assertIn('fixed', json.dumps(read_history.snapshot(resolved)))


if __name__ == "__main__":
    unittest.main()
