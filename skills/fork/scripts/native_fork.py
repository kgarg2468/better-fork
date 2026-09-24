"""Provider-owned native forks. No inference, source writes, or automatic retries."""
from __future__ import annotations

import json
import contextlib
import os
import selectors
import subprocess
import time
from pathlib import Path

from history_adapters import load_rows, codex_boundary, claude_chain, claude_boundary
from resolve_session import IDENTIFIER_RE


class NativeForkError(ValueError):
    def __init__(self, code, creation_status="not_created", child_id=None):
        super().__init__(code)
        self.code = code
        self.creation_status = creation_status
        self.child_id = child_id


def plan_native(source, *, through_turn=None, model=None, effort=None, cwd=None):
    native = source.get("native_source", source)
    if not native.get("native_session_available") or native.get("provider") not in {"codex", "claude"}:
        raise NativeForkError("native_session_unavailable")
    provider = native["provider"]
    if effort is not None and effort not in ({"minimal", "low", "medium", "high", "xhigh"} if provider == "codex" else {"low", "medium", "high", "xhigh", "max"}):
        raise NativeForkError("unsupported_effort")
    if model is not None and (not model.strip() or model.startswith("-") or "\n" in model):
        raise NativeForkError("invalid_model")
    rows = load_rows(native["native_record"], metadata_only=True)
    if provider == "codex":
        boundary, _ = codex_boundary(rows, through_turn)
    else:
        rows, _ = claude_chain(rows)
        boundary, _ = claude_boundary(rows, through_turn)
    target = Path(cwd or native.get("cwd") or os.getcwd()).resolve()
    if not target.is_dir():
        raise NativeForkError("workspace_unavailable")
    return {"provider": provider, "parent_session_id": native["native_session_id"],
            "boundary": boundary, "boundary_namespace": provider, "model": model,
            "effort": effort, "cwd": str(target), "source_cwd": native.get("cwd"),
            "native_session_created": False, "host_thread_created": False,
            "model_or_api_called": False, "workspace_isolated": False,
            "mapping_note": source.get('native_mapping_note'),
            "source_host": source.get("input_kind", provider)}


class CodexRPC:
    """Bounded JSON-lines RPC, including notifications and denied server requests."""
    def __init__(self, command, timeout):
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.DEVNULL, bufsize=0)
        except OSError:
            raise NativeForkError("codex_unavailable") from None
        self.timeout = timeout
        self.buffer = b""
        self.sequence = 0
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)

    def send(self, value):
        self.process.stdin.write((json.dumps(value) + "\n").encode())
        self.process.stdin.flush()

    def line(self, deadline):
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.selector.select(remaining):
                raise NativeForkError("native_timeout")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise NativeForkError("native_disconnected")
            self.buffer += chunk
            if len(self.buffer) > 64 * 1024 * 1024:
                raise NativeForkError("native_response_too_large")
        line, self.buffer = self.buffer.split(b"\n", 1)
        try:
            value = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            raise NativeForkError("invalid_native_response") from None
        if not isinstance(value, dict):
            raise NativeForkError("invalid_native_response")
        return value

    def request(self, method, params):
        self.sequence += 1
        identifier = self.sequence
        self.send({"id": identifier, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            response = self.line(deadline)
            if "method" in response:
                if "id" in response:
                    self.send({"id": response["id"], "error": {"code": -32601, "message": "Better Fork does not execute tools or approvals"}})
                continue
            if response.get("id") == identifier:
                if "error" in response:
                    raise NativeForkError("native_request_rejected")
                result = response.get("result")
                if not isinstance(result, dict):
                    raise NativeForkError("invalid_native_response")
                return result
        raise NativeForkError("native_timeout")

    def close(self):
        self.selector.close()
        with contextlib.suppress(OSError):
            self.process.stdin.close()
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    self.process.kill()
                self.process.wait()
        with contextlib.suppress(OSError):
            self.process.stdout.close()


def _codex_fork(plan, command, timeout):
    rpc = CodexRPC(command, timeout)
    dispatched = False
    child = None
    try:
        rpc.request("initialize", {"clientInfo": {"name": "better_fork", "version": "1.0.0"}, "capabilities": {}})
        rpc.send({"method": "initialized"})
        params = {"threadId": plan["parent_session_id"], "lastTurnId": plan["boundary"], "cwd": plan["cwd"]}
        if plan["model"]:
            params["model"] = plan["model"]
        if plan["effort"]:
            params["config"] = {"model_reasoning_effort": plan["effort"]}
        dispatched = True
        response = rpc.request("thread/fork", params)
        thread = response.get('thread')
        if not isinstance(thread, dict):
            raise NativeForkError('invalid_native_response')
        child = _valid_child(thread.get('id'), plan)
        if child is None:
            raise NativeForkError('invalid_child_id')
        verified = rpc.request('thread/read', {'threadId': child, 'includeTurns': False})
        if not isinstance(verified.get('thread'), dict) or verified['thread'].get('id') != child:
            raise NativeForkError('child_persistence_unverified')
        return child
    except (NativeForkError, OSError, ValueError) as exc:
        raise NativeForkError(getattr(exc, "code", "native_transport_failed"), "unknown" if dispatched else "not_created", child) from None
    finally:
        rpc.close()


def _claude_fork(plan, command, timeout):
    request = {"session_id": plan["parent_session_id"], "cwd": plan["source_cwd"], "through_turn": plan["boundary"]}
    try:
        result = subprocess.run(command, input=json.dumps(request), text=True, capture_output=True, timeout=timeout, check=False)
    except OSError:
        raise NativeForkError("claude_sdk_unavailable") from None
    except subprocess.TimeoutExpired:
        raise NativeForkError("native_timeout", "unknown") from None
    try:
        response = json.loads(result.stdout)
    except ValueError:
        raise NativeForkError("invalid_native_response", "unknown") from None
    if not isinstance(response, dict):
        raise NativeForkError("invalid_native_response", "unknown")
    child = _valid_child(response.get('session_id'), plan)
    if result.returncode or not response.get("ok"):
        code = response.get("error")
        safe = {"claude_sdk_unavailable", "claude_sdk_fork_unsupported", "claude_source_unavailable", "claude_boundary_unavailable"}
        if code in safe:
            raise NativeForkError(code)
        raise NativeForkError("claude_native_fork_failed", "unknown", child)
    if response.get("persisted") is not True:
        raise NativeForkError("child_persistence_unverified", "unknown", child)
    return response.get("session_id")


def _valid_child(identifier, plan):
    if isinstance(identifier, str) and IDENTIFIER_RE.fullmatch(identifier) and identifier != plan['parent_session_id']:
        return identifier
    return None


def execute_native(plan, *, codex_command=None, claude_command=None, timeout=30):
    if timeout <= 0 or timeout > 300:
        raise NativeForkError("invalid_timeout")
    if plan["provider"] == "codex":
        child = _codex_fork(plan, codex_command or ["codex", "app-server", "--listen", "stdio://"], timeout)
        resume = ["codex", "resume", "-C", plan["cwd"]]
        if plan["model"]:
            resume += ["--model", plan["model"]]
        if plan["effort"]:
            resume += ["-c", "model_reasoning_effort=" + json.dumps(plan["effort"])]
        resume.append(child)
    elif plan["provider"] == "claude":
        child = _claude_fork(plan, claude_command or ["node", str(Path(__file__).with_name("claude_native.mjs"))], timeout)
        resume = ["claude", "--resume", child]
        if plan["model"]:
            resume += ["--model", plan["model"]]
        if plan["effort"]:
            resume += ["--effort", plan["effort"]]
    else:
        raise NativeForkError("unsupported_native_provider")
    if not isinstance(child, str) or not IDENTIFIER_RE.fullmatch(child) or child == plan["parent_session_id"]:
        raise NativeForkError("invalid_child_id", "unknown")
    return {**plan, "native_session_created": True, "child_session_id": child,
            "resume_argv": resume, "resume_cwd": plan["cwd"],
            "model_application": "on_resume" if plan["provider"] == "claude" else "fork_configuration",
            "note": "Native conversation created. No T3 UI thread or isolated workspace was created."}
