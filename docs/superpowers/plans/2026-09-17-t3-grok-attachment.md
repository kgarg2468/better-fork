# T3 and Grok Attachment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach finalized public history from T3 threads, including Grok, while preserving native Claude Code and Codex behavior.

**Architecture:** Resolve T3 IDs against the read-only T3 SQLite projections and route T3 history reads through `projection_thread_messages`. Keep native launch metadata exclusive to native Claude Code and Codex IDs.

**Tech Stack:** Python 3 standard library (`sqlite3`, `unittest`), Markdown skill documentation.

## Global Constraints

- T3 database access is read-only and query-only.
- Only finalized `user` and `assistant` text is attachable.
- Grok attachment must not claim a native Grok fork or child session.
- Existing native Claude Code and Codex behavior must remain compatible.

---

### Task 1: Resolve T3 thread metadata

**Files:**
- Modify: `skills/fork/scripts/resolve_session.py`
- Modify: `skills/fork/scripts/test_resolve_session.py`

**Interfaces:**
- Consumes: T3 home directory containing `userdata/state.sqlite`.
- Produces: `resolve_session(..., t3_home=Path)` results with `input_kind == "t3"`, provider/workspace/model/boundary metadata, and no native launch claim.

- [x] **Step 1: Write failing synthetic SQLite tests**

Add a Grok T3 thread with a completed turn and assert provider, cwd, model,
boundary, attachment availability, and absent native launch metadata.

- [x] **Step 2: Run the resolver tests and verify the new test fails**

Run: `(cd skills/fork/scripts && python3 -m unittest test_resolve_session.py -v)`

Expected: failure because `resolve_session` does not accept or resolve T3 state.

- [x] **Step 3: Implement the minimal read-only T3 resolver**

Add `_t3_resolution`, guarded SQLite opening, provider normalization, model JSON
parsing, latest-turn boundary lookup, `t3_home`, and `--kind t3` support.

- [x] **Step 4: Run resolver tests and verify they pass**

Run: `(cd skills/fork/scripts && python3 -m unittest test_resolve_session.py -v)`

Expected: all resolver tests pass.

### Task 2: Read provider-neutral T3 history

**Files:**
- Modify: `skills/fork/scripts/read_history.py`
- Create: `skills/fork/scripts/test_read_history.py`

**Interfaces:**
- Consumes: a T3 resolver result whose `source_record` is `state.sqlite` and whose `t3_thread_id` identifies the thread.
- Produces: ordered `{role, text}` records for finalized user/assistant messages only.

- [x] **Step 1: Write failing history tests**

Create finalized user/assistant rows plus reasoning, streaming, and out-of-order
rows. Assert chronological output and exclusion of non-public rows.

- [x] **Step 2: Run the history tests and verify the new test fails**

Run: `(cd skills/fork/scripts && python3 -m unittest test_read_history.py -v)`

Expected: failure because T3 results have no native record reader.

- [x] **Step 3: Implement the minimal T3 history reader**

Query `projection_thread_messages` with role and streaming predicates, order by
`created_at, message_id`, and pass every emitted text through secret rejection.

- [x] **Step 4: Run the full Python suite**

Run: `python3 -m unittest discover -s skills/fork/scripts -p 'test_*.py' -v`

Expected: all tests pass.

### Task 3: Update the skill contract and validate the reported case

**Files:**
- Modify: `skills/fork/SKILL.md`
- Modify: `skills/fork/references/workflow.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: executable T3 attachment behavior from Tasks 1 and 2.
- Produces: accurate discovery, invocation, attachment, and native-fork boundaries.

- [x] **Step 1: Update instructions and public documentation**

Document T3, Grok, Claude Code, and Codex attachment; retain `$fork` as the
Codex invocation; state that T3 IDs are attachment-only and native forks require
a native Claude Code or Codex ID.

- [x] **Step 2: Validate skill structure and run the full suite**

Run: `python3 /absolute/path/to/skill-creator/scripts/quick_validate.py skills/fork`

Run: `python3 -m unittest discover -s skills/fork/scripts -p 'test_*.py' -v`

Expected: validation succeeds and all tests pass.

- [x] **Step 3: Smoke-test the reported Grok thread read-only**

Run: `python3 skills/fork/scripts/resolve_session.py fc9817b3-f5b0-40ca-8c86-933844c4177e --pretty`

Run: `python3 skills/fork/scripts/read_history.py fc9817b3-f5b0-40ca-8c86-933844c4177e --limit 1`

Expected: provider `grok`, completed boundary, and one public history record with
no database mutation.

- [ ] **Step 4: Review the diff, commit, push, and open a PR**

Review `git diff --check`, `git diff --stat`, and the full diff; commit the
verified files, push `feat/t3-grok-attachment`, and create a PR describing the
attachment/native boundary.

- [ ] **Step 5: Run PR Watch**

Detect CI and automated-review surfaces, dispatch the requested low-effort Luna
watcher, and report the first-wave result without auto-fixing findings.
