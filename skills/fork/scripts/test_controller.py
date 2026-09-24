from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_portable_history import codex_log, claude_log


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("better_fork"), "no portable fork controller")
        import better_fork
        return better_fork

    def setup_source(self, provider="codex"):
        identifier = "11111111-2222-4333-8444-555555555555"
        folder = self.root / provider / ("sessions" if provider == "codex" else "projects") / "test"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (("rollout-" if provider == "codex" else "") + identifier + ".jsonl")
        rows = codex_log() if provider == "codex" else claude_log()
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return identifier, path

    def invoke(self, args):
        module = self.module()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = module.main(args)
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def attach(self, provider="codex", receiver="current"):
        identifier, path = self.setup_source(provider)
        output = self.root / (provider + "-snapshot")
        code, result = self.invoke(["attach", identifier, "--kind", provider, "--codex-home", str(self.root / "codex"), "--claude-home", str(self.root / "claude"), "--t3-home", str(self.root / "absent-t3"), "--receiver", receiver, "--output", str(output), "--limit", "1"])
        self.assertEqual(code, 0, result)
        return result, path, output

    def test_native_sources_work_without_t3(self):
        for provider in ["codex", "claude"]:
            result, path, output = self.attach(provider)
            self.assertEqual(result["source"]["provider"], provider)
            self.assertFalse(result["native_session_created"])
            self.assertEqual(os.stat(output).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(output / "reviewed-history.json").st_mode & 0o777, 0o600)

    def test_cross_harness_transfer_does_not_claim_native_clone(self):
        result, _, _ = self.attach("codex", "claude")
        self.assertEqual(result["metadata"]["receiver"], "claude")
        self.assertEqual(result["mode"], "attach")
        self.assertFalse(result["host_thread_created"])

    def test_pagination_uses_snapshot_after_source_changes(self):
        result, path, output = self.attach()
        path.write_text("changed source", encoding="utf-8")
        all_records = list(result["records"])
        while result["next_argv"]:
            code, result = self.invoke(result["next_argv"][2:])
            self.assertEqual(code, 0)
            all_records.extend(result["records"])
        self.assertIn("3 tests passed", json.dumps(all_records))
        self.assertNotIn("changed source", json.dumps(all_records))

    def test_corruption_fails_closed(self):
        _, _, output = self.attach()
        (output / "reviewed-history.json").write_text("{}", encoding="utf-8")
        code, result = self.invoke(["read", str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "artifact_hash_mismatch")

    def test_explicit_excerpts_offer_exact_recovery(self):
        _, _, output = self.attach()
        code, page = self.invoke(["read", str(output), "--offset", "1", "--max-chars", "30"])
        self.assertEqual(code, 0)
        self.assertTrue(page["records"][0]["excerpted"])
        code, recovered = self.invoke(page["records"][0]["retrieve_argv"][2:])
        self.assertEqual(code, 0)
        self.assertIn("3 tests passed", recovered["records"][0]["text"])

    def test_dynamic_bridge_accepts_agent_selection_and_preserves_archive(self):
        _, _, output = self.attach()
        history = json.loads((output / "reviewed-history.json").read_text())
        selection = self.root / "selection.json"
        user_ids = [r["id"] for r in history["records"] if r["role"] == "user"]
        selection.write_text(json.dumps({"retain_ids": user_ids, "summary_ids": [], "summary_text": ""}))
        task = self.root / "task.txt"
        task.write_text("Explore a different parser API")
        bundle = self.root / "dynamic"
        code, result = self.invoke(["dynamic", str(output), "--selection", str(selection), "--next-task-file", str(task), "--output", str(bundle), "--reviewed-public-history"])
        self.assertEqual(code, 0, result)
        self.assertFalse(result["native_session_created"])
        archived = json.loads((bundle / "reviewed-history.json").read_text())
        self.assertEqual(archived, history)

    def test_dynamic_requires_review_declaration(self):
        _, _, output = self.attach()
        code, result = self.invoke(["dynamic", str(output), "--selection", str(self.root / "missing"), "--next-task-file", str(self.root / "missing"), "--output", str(self.root / "bundle")])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "reviewed_public_history_declaration_required")

    def test_unknown_retrieval_id_fails(self):
        _, _, output = self.attach()
        code, result = self.invoke(["retrieve", str(output), "--id", "missing"])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "unknown_id")

    def test_existing_output_is_never_overwritten(self):
        _, _, output = self.attach()
        code, result = self.invoke(["attach", "11111111-2222-4333-8444-555555555555", "--kind", "codex", "--codex-home", str(self.root / "codex"), "--output", str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"], "output_already_exists")

    def test_copied_skill_cli_works_from_an_unrelated_workspace(self):
        skill = self.root / "installed-fork"
        shutil.copytree(Path(__file__).resolve().parents[1], skill,
                        ignore=shutil.ignore_patterns("node_modules", "__pycache__"))
        identifier, _ = self.setup_source()
        receiver = self.root / "receiver"
        receiver.mkdir()
        command = [sys.executable, "-B", str(skill / "scripts" / "better_fork.py"),
                   "attach", identifier, "--kind", "codex", "--codex-home", str(self.root / "codex"),
                   "--output", str(self.root / "installed-snapshot"), "--limit", "1"]
        result = subprocess.run(command, cwd=receiver, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        first = json.loads(result.stdout)
        self.assertTrue(first["next_argv"][1].startswith(str(skill)))
        following = subprocess.run(first["next_argv"], cwd=receiver, text=True, capture_output=True)
        self.assertEqual(following.returncode, 0, following.stderr)
        self.assertIn("3 tests passed", following.stdout)


if __name__ == "__main__":
    unittest.main()
