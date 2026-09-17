# T3 and Grok Attachment Design

## Goal

Allow `$fork T3_THREAD_ID` to attach finalized public conversation history from
T3 threads, including Grok threads, to the current chat. Preserve native Claude
Code and Codex session handling for native IDs.

## Architecture

Use T3's read-only `userdata/state.sqlite` projections as the provider-neutral
source of truth. `projection_threads`, `projection_projects`,
`projection_thread_sessions`, and `projection_turns` provide source metadata;
`projection_thread_messages` provides ordered public messages. The provider
event logs remain diagnostic artifacts and are not required for attachment.

The resolver accepts a T3 thread ID and returns `input_kind: t3`, the normalized
provider name, workspace/model/boundary metadata, and an attachment-capable
source locator. A T3 result does not claim a native provider session or launch
command. Separate native forks continue to require a native Claude Code or
Codex session ID.

The history reader queries finalized rows ordered by creation time and message
ID, retaining only `user` and `assistant` roles. It excludes reasoning, tool
records, streaming rows, attachments, provider instructions, and other private
state. Existing secret rejection remains the final content gate.

## Errors and safety

- Open T3 state with SQLite URI `mode=ro` and `PRAGMA query_only=ON`.
- Reject symlinked, missing, malformed, or incompatible state databases.
- Return `session_not_found` for an unknown ID and a specific unreadable-state
  error when T3 state exists but cannot be queried safely.
- Never write T3 state or imply that attachment created a native child session.

## Verification

Synthetic SQLite fixtures cover Grok metadata resolution, completed boundaries,
provider-independent history ordering, role filtering, streaming exclusion, and
the unchanged native Claude/Codex paths. The real reported Grok thread is used
only for a read-only smoke test after the synthetic suite passes.
