from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from test_portable_history import codex_log, claude_log


class NativeForkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("native_fork"), "no executable native fork adapter")
        import native_fork
        return native_fork

    def source(self, provider):
        path = self.root / "source.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in (codex_log() if provider == "codex" else claude_log())), encoding="utf-8")
        return {"input_kind": provider, "provider": provider, "native_session_available": True, "native_session_id": "parent-id", "native_record": str(path), "cwd": str(self.root)}

    def server(self, code):
        path = self.root / "fake.py"
        path.write_text(code, encoding="utf-8")
        return [sys.executable, str(path)]

    def test_native_plan_pins_last_completed_boundary_without_launching(self):
        module = self.module()
        source = self.source("codex")
        before = Path(source["native_record"]).read_bytes()
        plan = module.plan_native(source, model="receiver-model", effort="high")
        self.assertEqual(plan["boundary"], "turn-1")
        self.assertEqual(plan["model"], "receiver-model")
        self.assertFalse(plan["native_session_created"])
        self.assertEqual(before, Path(source["native_record"]).read_bytes())

    def test_codex_adapter_uses_rpc_and_returns_actual_child(self):
        module = self.module()
        command = self.server('''import json, sys
for line in sys.stdin:
    req = json.loads(line)
    if req.get("method") == "initialize":
        print(json.dumps({"id": req["id"], "result": {"userAgent": "test"}}), flush=True)
    elif req.get("method") == "thread/fork":
        p = req["params"]
        assert p["threadId"] == "parent-id" and p["lastTurnId"] == "turn-1"
        assert p["model"] == "receiver-model" and p["config"]["model_reasoning_effort"] == "high"
        print(json.dumps({"method":"thread/started","params":{"thread":{"id":"child-id"}}}), flush=True)
        print(json.dumps({"id":req["id"],"result":{"thread":{"id":"child-id"}}}), flush=True)
    elif req.get("method") == "thread/read":
        print(json.dumps({"id":req["id"],"result":{"thread":{"id":"child-id"}}}), flush=True)
''')
        plan = module.plan_native(self.source("codex"), model="receiver-model", effort="high")
        result = module.execute_native(plan, codex_command=command, timeout=3)
        self.assertEqual(result["child_session_id"], "child-id")
        self.assertTrue(result["native_session_created"])
        self.assertFalse(result["host_thread_created"])
        self.assertFalse(result["model_or_api_called"])
        self.assertIn("receiver-model", result["resume_argv"])

    def test_parent_id_is_never_accepted_as_child(self):
        module = self.module()
        command = self.server('''import json,sys
for line in sys.stdin:
    q=json.loads(line)
    if "id" in q:
        print(json.dumps({"id":q["id"],"result":{"thread":{"id":"parent-id"}}}),flush=True)
''')
        with self.assertRaisesRegex(module.NativeForkError, "invalid_child_id"):
            module.execute_native(module.plan_native(self.source("codex")), codex_command=command, timeout=3)

    def test_timeout_is_ambiguous_not_reported_as_not_created(self):
        module = self.module()
        command = self.server('''import json,sys,time
for line in sys.stdin:
    q=json.loads(line)
    if q.get("method")=="initialize":
        print(json.dumps({"id":q["id"],"result":{}}),flush=True)
    elif q.get("method")=="thread/fork":
        time.sleep(20)
''')
        with self.assertRaises(module.NativeForkError) as error:
            module.execute_native(module.plan_native(self.source("codex")), codex_command=command, timeout=0.15)
        self.assertEqual(error.exception.creation_status, "unknown")

    def test_claude_adapter_uses_sdk_bridge_no_prompt_or_model_call(self):
        module = self.module()
        command = self.server('''import json,sys
q=json.load(sys.stdin)
assert q["session_id"]=="parent-id" and q["through_turn"]=="done-1"
assert "prompt" not in q
print(json.dumps({"ok":True,"session_id":"child-id","persisted":True}))
''')
        plan = module.plan_native(self.source("claude"), model="claude-opus-5-5", effort="high")
        result = module.execute_native(plan, claude_command=command, timeout=3)
        self.assertEqual(result["resume_argv"], ["claude", "--resume", "child-id", "--model", "claude-opus-5-5", "--effort", "high"])
        self.assertEqual(result["model_application"], "on_resume")
        self.assertFalse(result["model_or_api_called"])

    def test_t3_id_without_native_mapping_does_not_fabricate_child(self):
        module = self.module()
        with self.assertRaisesRegex(module.NativeForkError, "native_session_unavailable"):
            module.plan_native({"input_kind": "t3", "native_session_available": False})

    def test_missing_binary_reports_not_created(self):
        module = self.module()
        with self.assertRaises(module.NativeForkError) as error:
            module.execute_native(module.plan_native(self.source("codex")), codex_command=[str(self.root / "missing")])
        self.assertEqual(error.exception.creation_status, "not_created")

    def test_known_claude_child_id_survives_failed_verification(self):
        module = self.module()
        command = self.server('''import json,sys
json.load(sys.stdin)
print(json.dumps({"ok":False,"error":"claude_fork_result_unknown","session_id":"child-id"}))
''')
        with self.assertRaises(module.NativeForkError) as error:
            module.execute_native(module.plan_native(self.source('claude')), claude_command=command)
        self.assertEqual(error.exception.creation_status, 'unknown')
        self.assertEqual(error.exception.child_id, 'child-id')

    def test_invalid_codex_thread_shape_is_controlled(self):
        module = self.module()
        command = self.server('''import json,sys
for line in sys.stdin:
    q=json.loads(line)
    if "id" in q:
        print(json.dumps({"id":q["id"],"result":{"thread":[]}}),flush=True)
''')
        with self.assertRaises(module.NativeForkError):
            module.execute_native(module.plan_native(self.source('codex')), codex_command=command, timeout=3)


if __name__ == "__main__":
    unittest.main()
