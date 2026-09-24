from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import read_history


def codex_log():
    return [
        {"type": "session_meta", "payload": {"cwd": "/repo"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "provider bootstrap"}]}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-1"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "fix the parser"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "call-1", "arguments": '{"cmd":"pytest"}'}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call-1", "output": "3 tests passed"}},
        {"type": "response_item", "payload": {"type": "reasoning", "text": "private thinking"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "parser fixed"}]}},
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-1"}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "turn-2"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "unfinished prompt"}]}},
    ]


def claude_log():
    return [
        {"type": "user", "uuid": "user-1", "parentUuid": None, "message": {"role": "user", "content": "fix the parser"}},
        {"type": "assistant", "uuid": "assistant-1", "parentUuid": "user-1", "message": {"role": "assistant", "stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "call-1", "name": "Bash", "input": {"command": "pytest"}}]}},
        {"type": "user", "uuid": "tool-1", "parentUuid": "assistant-1", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call-1", "content": "3 tests passed"}]}},
        {"type": "assistant", "uuid": "done-1", "parentUuid": "tool-1", "message": {"role": "assistant", "stop_reason": "end_turn", "content": [{"type": "thinking", "thinking": "private thinking"}, {"type": "text", "text": "parser fixed"}]}},
        {"type": "user", "uuid": "user-2", "parentUuid": "done-1", "message": {"role": "user", "content": "unfinished prompt"}},
    ]


class PortableHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def source(self, provider, records):
        path = self.root / (provider + ".jsonl")
        path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        return {"input_kind": provider, "provider": provider, "input_id": "source-session", "native_session_id": "source-session", "native_record": str(path), "cwd": str(self.root)}

    def collect(self, provider, records, **kwargs):
        # Existing public reader gains the structured snapshot entry point.
        self.assertTrue(callable(getattr(read_history, "snapshot", None)), "missing structured, completed-boundary history snapshot")
        return read_history.snapshot(self.source(provider, records), **kwargs)

    def test_codex_stops_before_active_head_and_preserves_tool_pair(self):
        result = self.collect("codex", codex_log())
        text = json.dumps(result["history"])
        self.assertNotIn("unfinished prompt", text)
        self.assertNotIn("provider bootstrap", text)
        self.assertNotIn("private thinking", text)
        self.assertIn("3 tests passed", text)
        tools = [r for r in result["history"]["records"] if r["role"] == "tool"]
        self.assertEqual(len(tools), 1)
        self.assertIn("pytest", tools[0]["text"])
        self.assertEqual(result["history"]["source"]["boundary"], "turn-1")

    def test_claude_stops_before_active_head_and_pairs_tools(self):
        result = self.collect("claude", claude_log())
        text = json.dumps(result["history"])
        self.assertNotIn("unfinished prompt", text)
        self.assertNotIn("private thinking", text)
        self.assertIn("3 tests passed", text)
        self.assertEqual(result["history"]["source"]["boundary"], "done-1")

    def test_selected_boundary_excludes_later_completed_turn(self):
        rows = codex_log() + [{"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-2"}}]
        result = self.collect("codex", rows, through_turn="turn-1")
        self.assertNotIn("unfinished prompt", json.dumps(result))
        self.assertEqual(result["history"]["source"]["boundary"], "turn-1")

    def test_invalid_or_incomplete_boundary_fails_closed(self):
        self.assertTrue(callable(getattr(read_history, "snapshot", None)), "missing boundary validation")
        for boundary in ["missing", "turn-2"]:
            with self.subTest(boundary=boundary), self.assertRaisesRegex(ValueError, "boundary"):
                read_history.snapshot(self.source("codex", codex_log()), through_turn=boundary)

    def test_claude_uses_parent_chain_not_discarded_branch(self):
        rows = claude_log()
        rows.insert(4, {"type": "assistant", "uuid": "discarded", "parentUuid": "tool-1", "message": {"role": "assistant", "stop_reason": "end_turn", "content": "wrong branch"}})
        result = self.collect("claude", rows)
        self.assertNotIn("wrong branch", json.dumps(result))

    def test_claude_turn_duration_marks_terminal_assistant(self):
        rows = claude_log()[:4]
        rows[-1]["message"]["stop_reason"] = None
        rows.append({"type": "system", "subtype": "turn_duration", "uuid": "duration", "parentUuid": "done-1", "durationMs": 5})
        result = self.collect("claude", rows)
        self.assertEqual(result["history"]["source"]["boundary"], "done-1")

    def test_attachment_references_without_inline_binary(self):
        rows = claude_log()
        rows[0]["message"]["content"] = [{"type": "text", "text": "inspect screenshot"}, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "BINARY_CONTENT"}}]
        result = self.collect("claude", rows)
        text = json.dumps(result)
        self.assertIn("image/png", text)
        self.assertNotIn("BINARY_CONTENT", text)

    def test_secrets_in_tool_output_are_withheld_without_blocking_safe_history(self):
        self.assertTrue(callable(getattr(read_history, "snapshot", None)), "missing structured secret screening")
        rows = codex_log()
        rows[5]["payload"]["output"] = "sk-" + "x" * 30
        result = read_history.snapshot(self.source("codex", rows))
        self.assertNotIn("sk-" + "x" * 30, json.dumps(result))
        self.assertIn("parser fixed", json.dumps(result))
        self.assertIn("secret_like_tool_record_withheld", result["metadata"]["omissions"])
        self.assertTrue(result["metadata"]["withheld_record_ids"])
        self.assertEqual(result["history"]["source"]["coverage"], "partial")

    def test_code_read_false_positive_is_disclosed_not_exported(self):
        rows = codex_log()
        rows[5]["payload"]["output"] = 'password = os.environ.get("DB_PASSWORD")'
        result = self.collect("codex", rows)
        self.assertNotIn("os.environ", json.dumps(result))
        self.assertIn("parser fixed", json.dumps(result))

    def test_secrets_in_user_text_still_fail_closed(self):
        rows = codex_log()
        rows[3]["payload"]["content"][0]["text"] = "sk-" + "x" * 30
        with self.assertRaisesRegex(Exception, "secret_like_value"):
            read_history.snapshot(self.source("codex", rows))

    def test_codex_image_tool_output_is_a_reference_only(self):
        rows = codex_log()
        rows[5]["payload"]["output"] = [{"type": "input_image", "image_url": "data:image/png;base64,PRIVATE_BINARY"}]
        result = self.collect("codex", rows)
        self.assertNotIn("PRIVATE_BINARY", json.dumps(result))
        self.assertIn("attachment_reference", json.dumps(result))

    def test_claude_compaction_is_partial_coverage(self):
        rows = claude_log()
        rows[0]["parentUuid"] = "compact"
        rows.insert(0, {"type": "system", "subtype": "compact_boundary", "uuid": "compact", "parentUuid": None, "logicalParentUuid": "older-history"})
        result = self.collect("claude", rows)
        self.assertEqual(result["history"]["source"]["coverage"], "partial")

    def test_null_claude_content_is_handled_without_traceback(self):
        rows = claude_log()
        rows[-1]["message"]["content"] = None
        result = self.collect("claude", rows)
        self.assertEqual(result["history"]["source"]["boundary"], "done-1")

    def test_stable_ids_and_schema_feed_existing_selector(self):
        import fork_context
        result = self.collect("codex", codex_log())
        history = result["history"]
        path = self.root / "history.json"
        path.write_text(json.dumps(history), encoding="utf-8")
        loaded, _ = fork_context._load_history(path)
        self.assertEqual(loaded, history)
        self.assertEqual(history, self.collect("codex", codex_log())["history"])

    def test_malformed_nested_native_record_is_a_controlled_error(self):
        rows = codex_log()
        rows[4]["payload"] = ["not an item"]
        with self.assertRaisesRegex(ValueError, "malformed_native_history"):
            read_history.snapshot(self.source("codex", rows))

    def test_codex_excludes_failed_turn_before_a_later_success(self):
        rows = codex_log()
        rows[8]["payload"]["type"] = "task_failed"
        rows += [{"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn-2"}}]
        result = self.collect("codex", rows)
        self.assertNotIn("parser fixed", json.dumps(result))
        self.assertNotIn("3 tests passed", json.dumps(result))
        self.assertIn("unfinished_turns_excluded", result["metadata"]["omissions"])

    def test_secret_in_excluded_future_turn_does_not_block_history(self):
        rows = codex_log()
        rows[-1]["payload"]["content"][0]["text"] = "sk-" + "x" * 30
        result = self.collect("codex", rows)
        self.assertNotIn("sk-", json.dumps(result))

    def test_large_inline_attachment_does_not_use_public_export_budget(self):
        from history_adapters import load_rows
        rows = claude_log()
        rows[0]['message']['content'] = [{'type': 'text', 'text': 'inspect screenshot'},
                                        {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'A' * (51 * 1024 * 1024)}}]
        source = self.source('claude', rows)
        result = read_history.snapshot(source)
        self.assertIn('image/png', json.dumps(result))
        self.assertLess(len(json.dumps(result)), 10000)
        metadata = load_rows(source['native_record'], metadata_only=True)
        self.assertLess(len(json.dumps(metadata)), 10000)

    def test_split_assistant_tool_rows_match_observed_claude_cli_shape(self):
        # Shape observed in a generated Claude Code 2.1.281 conversation, not
        # copied from personal history: split tool blocks share message.id.
        rows = claude_log()[:4]
        rows[1]['message']['id'] = 'shared-assistant-message'
        second_call = {'type': 'assistant', 'uuid': 'assistant-2', 'parentUuid': 'tool-1',
                       'message': {'id': 'shared-assistant-message', 'stop_reason': 'tool_use',
                                   'content': [{'type': 'tool_use', 'id': 'call-2', 'name': 'Read', 'input': {'file_path': '/fixture/second.txt'}}]}}
        second_result = {'type': 'user', 'uuid': 'tool-2', 'parentUuid': 'assistant-2',
                         'message': {'content': [{'type': 'tool_result', 'tool_use_id': 'call-2', 'content': 'second file content'}]}}
        rows[-1]['parentUuid'] = 'progress-2'
        rows[3:3] = [second_call, second_result, {'type': 'progress', 'uuid': 'progress-2', 'parentUuid': 'tool-2'}]
        result = self.collect('claude', rows)
        tools = [json.loads(r['text']) for r in result['history']['records'] if r['role'] == 'tool']
        self.assertEqual(len(tools), 2)
        self.assertTrue(all(r['result_available'] for r in tools))

    def test_legacy_rewrite_marker_is_not_silently_replayed(self):
        rows = codex_log()[:9] + [{'type': 'event_msg', 'payload': {'type': 'thread_rolled_back', 'num_turns': 1}}]
        with self.assertRaisesRegex(ValueError, 'native_history_rewrite'):
            read_history.snapshot(self.source('codex', rows))

    def test_tool_arguments_are_not_misidentified_as_attachment_blocks(self):
        rows = claude_log()
        rows[1]['message']['content'][0]['input'] = {'type': 'document', 'text': 'business data, not a binary attachment'}
        result = self.collect('claude', rows)
        self.assertIn('business data, not a binary attachment', json.dumps(result))

    def test_claude_list_tool_result_preserves_text_and_image_reference(self):
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                rows = claude_log()
                content = [{'type': 'text', 'text': 'subagent found the parser bug'}]
                if mixed:
                    content.append({'type': 'image', 'source': {'media_type': 'image/png', 'data': 'PRIVATE_BINARY'}})
                rows[2]['message']['content'][0]['content'] = content
                result = self.collect('claude', rows)
                self.assertIn('subagent found the parser bug', json.dumps(result))
                self.assertNotIn('PRIVATE_BINARY', json.dumps(result))
                if mixed:
                    self.assertIn('attachment_reference', json.dumps(result))

    def test_metadata_only_does_not_invent_completed_assistant_after_user_prompt(self):
        from history_adapters import load_rows, claude_chain, claude_boundary
        rows = claude_log()
        rows[3]['message']['stop_reason'] = None
        rows.append({'type': 'system', 'subtype': 'turn_duration', 'uuid': 'duration-2', 'parentUuid': 'user-2'})
        source = self.source('claude', rows)
        for metadata_only in (False, True):
            with self.subTest(metadata_only=metadata_only):
                chain, _ = claude_chain(load_rows(source['native_record'], metadata_only=metadata_only))
                with self.assertRaisesRegex(ValueError, 'completed_boundary_unavailable'):
                    claude_boundary(chain)


if __name__ == "__main__":
    unittest.main()
