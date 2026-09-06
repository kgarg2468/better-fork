---
name: fork
description: Continue work from an explicit completed session boundary while preserving the parent, using native host forks by default or an explicitly requested adaptive-context experiment.
---

# Fork

Create a real continuation from a known completed boundary. Preserve the parent session, repository state, user authority, and requested model.

This skill is normally discoverable automatically. In Codex, find skills with `/skills` and invoke this one as `$fork`; do not promise that `/fork` intercepts a client built-in. In Claude environments that discover skills, `/fork` may invoke it, but never override a native command of that name.

## Choose the mode

- Use a native host fork for ordinary continuation. It has no selector step or selection cost and is the default.
- Use fresh context only when explicitly requested, or when the user clearly changes direction and opts into the experiment. It is not a native fork.
- For an explicitly selected model-free direct method, read [references/direct.md](references/direct.md). For the explicitly selected legacy selector method, use the legacy selector section of [references/workflow.md](references/workflow.md).
- Read [references/workflow.md](references/workflow.md) before creating or handing off any fork.
- Read [references/evaluation.md](references/evaluation.md) only to design or interpret a context-transfer comparison.

## Invariants

- Check native capabilities first and prefer native host fork tools.
- Never claim a child exists without an actual child/session ID. Without a callable API, give an exact local CLI command or a handoff marked `not created`.
- A shared-workspace subagent is not necessarily a persistent, user-addressable interactive fork. Do not equate them.
- Do not fake T3 registration, write app databases, make UI changes, or silently continue the task in the parent.
- Resolve T3 thread IDs separately from native session IDs and name the exact completed boundary.
- Preserve explicitly requested models; never silently substitute or assume a selector is cheaper.
- Preserve the parent checkout and requested/current working-copy semantics. If shared versus isolated workspace materially matters and is unknown, clarify it. Never discard dirty or untracked work silently.
- A fork request authorizes the requested continuation, not unrelated exports, model calls, repository changes, or evaluation runs.

Report mode, provider/native ID, completed boundary, repository checkpoint and dirty-state handling, workspace semantics, requested model, child ID or `not created`, history coverage, and fallback.
