---
name: fork
description: Attach a previous T3, Grok, Claude Code, or Codex conversation to the current chat and continue its work; create a separate native fork only when requested.
---

# Fork

Create a real continuation from a known boundary. Accept a T3 thread ID or a native Claude Code or Codex session ID. Preserve the parent session, repository state, user authority, and requested model.

This skill is normally discoverable automatically. In Codex, find skills with `/skills` and invoke this one as `$fork`; do not promise that `/fork` intercepts a client built-in. In Claude environments that discover skills, `/fork` may invoke it, but never override a native command of that name.

## Choose the mode

“Fork this thread so I can continue here independently while the original stays
untouched” means current-chat attachment. This chat is already the separate
conversation. Run the history reader and continue here; do not launch another
session, browse for a fork button, or navigate to t3.chat (a different product
from T3 Code). Attachment preserves the source conversation but does not isolate
shared project files.

For attachment, a pending/running/interrupted source head is not a blocker.
The reader selects the last completed turn and returns `attachment_boundary`
and `attachment_note`. Follow `next_argv` until null to read all pages with the
same boundary. Disclose excluded unfinished turns. If reading fails,
report the concrete error without inventing a UI action or requiring a native
fork API.

- For `$fork ID`, “attach this session”, or ordinary continuation in a new chat, load the source conversation into the CURRENT chat. Keep the current model. Read the current-chat attachment section of the workflow and perform it; a native fork API is not required.
- Create a separate native session only when the user explicitly requests another session or a native fork.
- Use fresh context only when explicitly requested, or when the user clearly changes direction and opts into the experiment. It is not a native fork.
- For an explicitly selected model-free direct method, read [references/direct.md](references/direct.md). For the explicitly selected legacy selector method, use the legacy selector section of [references/workflow.md](references/workflow.md).
- Read [references/workflow.md](references/workflow.md) before creating or handing off any fork.

## Resolve the source ID first

For every supplied ID, run the bundled read-only resolver before choosing a provider or fork command:

```sh
python3 "$SKILL_ROOT/scripts/resolve_session.py" "$SESSION_ID" --pretty
```

`SKILL_ROOT` is the resolved directory containing this `SKILL.md`. The resolver accepts T3 thread IDs and native Claude Code or Codex IDs, returns the provider plus cwd, model, and boundary, and never mutates or launches anything. Native IDs also return launch arguments. Treat `input_kind`, `provider`, `native_session_available`, and `boundary` from its JSON as authoritative. A T3 result, including a Grok thread, is attachment-only and does not claim a native provider session. Never infer the source provider from the current agent. If resolution fails, stop with its error; do not try another provider blindly.

## Invariants

- For current-chat attachment, read history and continue here. Do not stop with “fork not created” or give CLI commands merely because a native fork API is absent.
- T3 thread IDs are attachment sources. A separate native fork requires a resolvable native Claude Code or Codex session ID.
- Never claim a child exists without an actual child/session ID. Without a callable API, give an exact local CLI command or a handoff marked `not created`.
- A shared-workspace subagent is not necessarily a persistent, user-addressable interactive fork. Do not equate them.
- Do not write app databases, make UI changes, or silently continue the task in the parent.
- Resolve every supplied ID with `scripts/resolve_session.py`; never infer its provider from the current agent.
- Preserve explicitly requested models; never silently substitute or assume a selector is cheaper.
- Preserve the parent checkout and requested/current working-copy semantics. If shared versus isolated workspace materially matters and is unknown, clarify it. Never discard dirty or untracked work silently.
- A fork request authorizes the requested continuation, not unrelated exports, model calls, repository changes, or evaluation runs.

For attachment, briefly report what work was recovered, the source ID, and any missing context. Say history was loaded into this chat; never claim a backend session merge. The detailed child-ID report applies only to separate native forks.
