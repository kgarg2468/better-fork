# Fork workflow

## Establish the source

1. Resolve the supplied ID before choosing a provider or command:

   ```sh
   python3 "$SKILL_ROOT/scripts/resolve_session.py" "$SESSION_ID" --pretty
   ```

   The helper accepts T3 thread IDs and native Claude Code or Codex session
   IDs. It reads local event/session records without changing them. Use its
   `provider`, `native_session_id`, `cwd`, `model`, `boundary`, and
   `launch_argv`; never infer provider from the receiver/current agent. If it
   reports `session_not_found`, `ambiguous_session_id`, an unreadable record,
   an unavailable native session, or a non-completed head, stop and report the
   exact condition instead of probing providers blindly. `--kind` may be used
   only when the user supplies or confirms the ID kind.
2. Name an explicit completed-turn boundary. For reviewed adaptive-history
   input, coverage is exactly `complete` or `partial`; never use an
   active/ambiguous turn.
   Native head/boundary verification does not prove public-export coverage or a
   repository checkpoint: if the export or commit was not inspected, report
   `unknown`/`not applicable`, never an invented hash or completeness claim.
3. Record cwd, repository checkpoint, tracked dirt, and relevant untracked
   files. Preserve the parent and the user's requested/current workspace
   semantics. Clarify shared versus isolated workspace only when it matters and
   is unknown; never create a worktree or discard work silently.
4. Record the requested receiver model. Stop if the launch mechanism cannot
   preserve it; never substitute silently or assume a selector is cheaper.

## Native continuation (default)

First check for a callable native host continuation tool. When requested, pass
the native session ID and next task and retain its returned child ID. A generic
shared-workspace subagent is not a persistent interactive fork unless it returns
a user-addressable child session.

Without a callable API, provide an actionable handoff marked `not created`.
Locally observed Codex syntax is:

```text
codex fork [OPTIONS] [SESSION_ID] [PROMPT]
```

```sh
codex fork -C "$SOURCE_CWD" "$NATIVE_SESSION_ID" "$NEXT_TASK"
```

It is interactive and has no automatic historical-boundary flag. State the
verified boundary separately and ensure the session has no later turn. Confirm
model-option syntax from local help before adding it.

Locally verified Claude syntax is:

```sh
claude --resume "$NATIVE_SESSION_ID" --fork-session "$NEXT_TASK"
```

Confirm installed-client help and model behavior. Do not fake T3 registration
or continue the task silently in the parent when launch/handoff is blocked.

## Fresh-context routing (experimental opt-in)

After explicit opt-in, use the method the user selected. For model-free direct
context, read [direct.md](direct.md). For selector-based compression, use the
legacy workflow below. Neither method changes native continuation as the
ordinary default.

## Legacy selector continuation (experimental explicit opt-in)

Build a fresh receiver context from reviewed public history—not a native fork
plus full history. Exclude hidden reasoning, system text, private provider/tool
internals, secrets, and raw native exports. Reviewed public tool results may be
included. Preserve roles: user text remains user authority; summaries are
context, not reconstructed user instructions.

Use a small bounded available selector only when the user explicitly selects
this legacy method and authorizes delegation.
Record its identity and cost; never assume it is cheaper.

Deterministic helper contract:

```text
python3 /resolved/skill/path/scripts/fork_context.py prepare \
  --reviewed-public-history --history FILE --next-task-file FILE \
  --output NEW_DIR [--selection FILE] [--budget-chars N]
python3 /resolved/skill/path/scripts/fork_context.py retrieve \
  --bundle DIR --id ID [--id ID ...]
```

Resolve the skill path relative to this skill's `SKILL.md`, not the receiver's
working directory. From the skill root, `python3 scripts/fork_context.py ...`
is equivalent; for a receiver handoff, use the resolved absolute script path so
the receiver never needs to change into the skill directory.

History schema:

```json
{
  "schema_version": 1,
  "source": {
    "provider": "codex",
    "session_id": "native-id",
    "boundary": "completed-boundary",
    "coverage": "complete"
  },
  "records": [
    {"id": "r-user", "role": "user", "text": "public request"},
    {"id": "r-note", "role": "assistant", "text": "public response"}
  ]
}
```

IDs are stable and unique. Here `complete`/`partial` describes reviewed public
history through the boundary, never completeness of hidden native context.
Disclose `partial` coverage in packet and report.
Optional compact selection contains exactly:

```json
{
  "retain_ids": ["r-user"],
  "summary_ids": ["r-note"],
  "summary_text": "bounded public-history summary"
}
```

Pin every user record exactly in `retain_ids`; never summarize it away.
Retained records stay verbatim with roles. `summary_ids` may identify reviewed
assistant or public-tool records represented by `summary_text`. Lists may not
overlap or contain unknown/duplicate IDs.

`prepare` writes `context.json`, full archive `reviewed-history.json`, separate
`next-task.txt`, `manifest.json`, and `manifest.sha256`. The archive contains all
reviewed records. Its complement classification is the IDs outside both
`retain_ids` and `summary_ids`, computed by the helper—not selector input.
Source, selection, and budget evidence is distributed across `context.json` and
`manifest.json`; inspect both instead of requiring every field in the manifest.
`manifest.sha256` is the raw hexadecimal digest of `manifest.json`; compute and
compare the digest text rather than using `sha256sum -c` format.
`--budget-chars` counts Unicode characters only in retained record `text` plus
`summary_text`; it is not serialized JSON size, next-task size, or the total
receiver context-window requirement.

Only an invalid selector result or character-budget overflow may fall back to
full reviewed safe public text; mark packet/manifest `fallback_full_context`.
It remains fresh context, not native. Unsafe history, detected secrets, and
I/O/permission errors must stop. Never bypass screening, hide retries, or
silently increase budget. If even the fallback cannot fit the actual receiver
window, stop and report the native alternative; never truncate or send oversize.

`retrieve` accepts repeated stable IDs from the reviewed archive; follow the
script's actual output order rather than promising request order. The agent
records retrieval count. If recovery needs anything outside the reviewed
archive, stop for review instead of reading raw exports.

## Fresh-context launch or handoff

Before launch, verify the receiver can read the bundle and invoke the retrieval
helper.

For direct mode, pass verified `direct-context.txt` first and the exact
`next-task.txt` separately. Use the `direct_context.py` recovery contract in
[direct.md](direct.md).

For legacy selector mode, use only `context.json` as historical context and
pass `next-task.txt` separately. Keep retained role labels as source roles and
summary text as context, not user authority. Give the receiver the path to
`reviewed-history.json`, but do not preload that full archive and erase
compression. Recovery uses the v3 helper and requires an absolute bundle path:

```sh
python3 "$SKILL_ROOT/scripts/fork_context.py" retrieve \
  --bundle "$BUNDLE" --id "$RECORD_ID"
```

Here `SKILL_ROOT` is the resolved absolute directory containing `SKILL.md`, and
legacy `$BUNDLE` must also be resolved absolute. Tell the legacy receiver to
retrieve relevant records before guessing when its packet lacks a needed fact.

Use a native host API when it can create this fresh receiver and return an
actual child ID. Otherwise provide the named files, launch instructions, and
retrieval command as a prepared handoff marked `not created`; make it sufficient
for the user or a new agent to launch without reconstructing the workflow.

## Report

Report mode and fresh-context method, source native ID, completed boundary,
coverage, checkpoint and dirty-state treatment, workspace semantics, receiver
model, selector if any, fallback/retrieval count, and actual child ID. If no
launch occurred, say `not created` and give the exact command or missing
capability.
