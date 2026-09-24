"""Opt-in, model-free smoke checks against installed provider runtimes.

Run with BETTER_FORK_RUN_NATIVE_SMOKE=1. Provider stores are temporary and no
credentials, real conversations, model requests, or project settings are used.
BETTER_FORK_CLAUDE_SDK may point to an installed SDK's sdk.mjs.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from native_fork import execute_native, plan_native
from test_portable_history import codex_log, claude_log


@unittest.skipUnless(os.environ.get("BETTER_FORK_RUN_NATIVE_SMOKE") == "1", "opt-in provider runtime smoke")
class NativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="better-fork-runtime-")
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / "project"
        self.workspace.mkdir()
        self.provider_config = {"CODEX_HOME": str(self.root / "codex"), "CLAUDE_CONFIG_DIR": str(self.root / "claude")}

    def tearDown(self):
        self.temp.cleanup()

    def fixture(self, provider):
        identifier = str(uuid.uuid4())
        if provider == "codex":
            path = self.root / "codex" / "sessions" / "2026" / "09" / "23" / ("rollout-2026-09-23T00-00-00-" + identifier + ".jsonl")
            rows = codex_log()
            rows[0]["payload"].update(id=identifier, timestamp="2026-09-23T00:00:00Z", cwd=str(self.workspace), originator="codex_cli_rs", cli_version="0.0.0", source="cli", model_provider="openai")
            for row in rows:
                row["timestamp"] = "2026-09-23T00:00:00Z"
        else:
            directory = re.sub(r'[^a-zA-Z0-9]', '-', str(self.workspace))
            path = self.root / "claude" / "projects" / directory / (identifier + ".jsonl")
            rows = claude_log()
            for row in rows:
                row.update(sessionId=identifier, cwd=str(self.workspace), timestamp="2026-09-23T00:00:00Z", version="2.1.281", isSidechain=False)
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        source = {"input_kind": provider, "provider": provider, "native_session_available": True,
                  "native_session_id": identifier, "native_record": str(path), "cwd": str(self.workspace)}
        return path, source

    @unittest.skipUnless(shutil.which("codex"), "Codex is not installed")
    def test_real_codex_completed_boundary_fork(self):
        path, source = self.fixture("codex")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with patch.dict(os.environ, self.provider_config):
            result = execute_native(plan_native(source), timeout=30)
        self.assertTrue(result["native_session_created"])
        self.assertNotEqual(result["child_session_id"], source["native_session_id"])
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        copies = list((self.root / "codex" / "sessions").rglob("*" + result["child_session_id"] + ".jsonl"))
        self.assertEqual(len(copies), 1)
        copied = copies[0].read_text()
        self.assertIn("3 tests passed", copied)
        self.assertNotIn("unfinished prompt", copied)

    @unittest.skipUnless(shutil.which("node"), "Node is not installed")
    def test_real_claude_sdk_completed_boundary_fork(self):
        path, source = self.fixture("claude")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        command = ["node", str(Path(__file__).with_name("claude_native.mjs"))]
        if os.environ.get("BETTER_FORK_CLAUDE_SDK"):
            command.append(os.environ["BETTER_FORK_CLAUDE_SDK"])
        with patch.dict(os.environ, self.provider_config):
            result = execute_native(plan_native(source), claude_command=command, timeout=30)
        self.assertTrue(result["native_session_created"])
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
        copies = list((self.root / "claude" / "projects").rglob(result["child_session_id"] + ".jsonl"))
        self.assertEqual(len(copies), 1)
        copied = copies[0].read_text()
        self.assertIn("3 tests passed", copied)
        self.assertNotIn("unfinished prompt", copied)


if __name__ == "__main__":
    unittest.main()
