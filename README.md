<h1 align="center">Better Fork</h1>

<p align="center">
  <strong>A better way to fork AI coding conversations.</strong>
</p>

<p align="center">
  Keep native history, continue across harnesses, or shape context around your next task.<br>
  Works with Codex, Claude Code, and T3 Code. No T3 installation required.
</p>

<p align="center">
  <a href="#install"><img src="https://img.shields.io/badge/install-one_command-blue" alt="One-command install"></a>
  <a href="#what-we-test"><img src="https://img.shields.io/badge/testing-boundaries_%26_real_forks-blue" alt="Tests cover history boundaries and real native forks"></a>
  <a href="#honest-limits"><img src="https://img.shields.io/badge/claims-bounded-orange" alt="Bounded claims"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#use-dynamic-mode">Dynamic mode</a> ·
  <a href="#what-we-test">What we test</a> ·
  <a href="#honest-limits">Honest limits</a>
</p>

<p align="center">
  <img src="docs/assets/conversation-handoff.svg" alt="A previous conversation contains your task, constraints, decisions, and progress. In your current chat, invoke $fork with its ID to load the public conversation and continue with your selected model and workspace." width="880">
</p>

You already explained the project once. Better Fork gives the next chat that history so you can get back to work.

## Why “Better” Fork?

Not every new direction needs the same context. Better Fork lets you preserve native history, bring supported history into another harness, or let an agent select context using your previous conversation, next task, and current project.

It builds **on** native forking, adding portability and task-specific continuation. One workflow, with a clear record of what was transferred or created.

## Install

Install the `fork` skill with the open skills installer:

```bash
npx skills add kgarg2468/better-fork --skill fork
```

In Codex, invoke it as `$fork`; `/fork` may be intercepted by the native client command. In Claude Code installations that expose skills as slash commands, use `/fork`.

You can also clone the repository and copy `skills/fork` into your agent's skills directory.

Attachment needs Python 3.9+ only. Native Codex forks also need the Codex CLI. Native Claude forks use Node 18+ and the optional official SDK; in your installed skill directory, run `npm install --ignore-scripts --no-audit --no-fund`. Neither native fork adapter makes a model call to create the child.

## How it works

In your receiving chat, invoke the skill with the previous conversation's ID:

```text
$fork YOUR_SESSION_ID
```

Better Fork finds the local source, freezes its completed history in a private snapshot, and loads it into this chat. Native sources include public tool calls and results, paired together. The agent recovers the task, constraints, decisions, and progress, checks current project files, and continues in your current model and workspace.

Codex and Claude Code work directly without T3 installed. T3 Code thread IDs (including Grok threads) are an additional source type. System/developer-role messages are excluded, but harness context stored as user text can remain. See [honest limits](#honest-limits) for transfer and workspace boundaries.

| Source | Attach into your current chat | Real native child |
| --- | --- | --- |
| Codex session ID | Public text and paired tool evidence | Codex app-server fork |
| Claude Code session ID | Public text and paired tool evidence | Claude Agent SDK fork |
| T3 Code thread ID | Public text, tool activity summaries, attachment references | Only with a stored provider ID found locally |

Attachment is portable across receiving harnesses; native creation stays within the source provider.

### Using a T3 Code thread ID

The thread ID shown by T3 Code identifies the conversation in T3 Code. It is distinct from the underlying Claude Code or Codex session ID. You can paste that T3 Code ID directly:

```text
$fork YOUR_T3_CODE_THREAD_ID
Continue this conversation here independently and leave the original chat untouched.
```

Your receiving chat is already separate. Better Fork reads the source without changing it or opening another app. A queued, running, or interrupted head is excluded in favor of the last completed turn. All pages come from the same frozen snapshot. Raw T3 activity payloads are not exported; public tool summaries are included. A thread with no completed history reports that limitation.

## Choose how to continue

Different next steps need different context. Loading history into the current chat is the default; separate native forks and fresh-context experiments are available when requested.

<p align="center">
  <img src="docs/assets/continuation-modes.svg" alt="Four choices: attach public conversation history to the current chat by default; explicitly request a native fork for a separate provider session; opt into direct context to transfer every reviewed public record; or opt into dynamic mode to keep, summarize, and archive reviewed context for a new task." width="880">
</p>

| Route | When it runs | Context behavior |
| --- | --- | --- |
| **Attach** | `$fork ID`; default | Loads a fixed public-history snapshot and available tool evidence here; keeps your current model/workspace |
| **Native** | Explicit native-child request | Executes the provider's fork and returns a real child ID; no inference during creation |
| **Direct (experimental)** | Explicit fresh-context opt-in | Transfers every reviewed public record, exactly and in order; no context selection |
| **Dynamic (experimental)** | Explicit dynamic-mode request | Builds agent-selected context for your next task, with a recoverable archive of reviewed records |

### Create a real native fork

Ask the skill to create a native child and specify your model/effort if needed. The controller also works directly (`SKILL_ROOT` is your installed `fork` directory):

```sh
python3 "$SKILL_ROOT/scripts/better_fork.py" native YOUR_SESSION_ID
python3 "$SKILL_ROOT/scripts/better_fork.py" native YOUR_SESSION_ID --execute
```

Without `--execute`, it only plans. Add `--through-turn` for an earlier completed provider boundary, and `--model` / `--effort` to preserve your receiver choices. Claude applies those choices on resume. The result includes the actual child ID, resume arguments, and working directory. A timeout after dispatch is reported as unknown, never automatically retried.

Codex uses [`thread/fork`](https://learn.chatgpt.com/docs/app-server); Claude uses the official [Agent SDK](https://code.claude.com/docs/en/agent-sdk/sessions). Native fidelity comes from those providers.

## Context for the next task

Changing direction? Dynamic mode lets an agent decide which reviewed context belongs in the next thread: retain useful records, summarize supporting details, and leave the rest available for retrieval.

### Use dynamic mode

Dynamic mode is experimental and opt-in. Start a new chat and specify the source, mode, and next task:

```text
$fork YOUR_SESSION_ID

Use dynamic mode for this fork.
My next task is: YOUR_NEXT_TASK
Select the context here. Ask before delegating to another agent.
```

The agent reviews the fixed history snapshot, your next task, and relevant current project files. It keeps every user record verbatim, retains useful assistant/tool evidence, summarizes supporting details, and archives the rest for retrieval. Paired native tool calls/results stay together. The controller validates and packages that selection; it does not secretly call a selector model.

Dynamic mode never runs from `$fork ID` alone. Only reviewed public records enter the context packet.

<p align="center">
  <img src="docs/assets/context-selection.svg" alt="Experimental dynamic-mode flow: reviewed public history and the next task inform an agent's selection. Every user record stays verbatim, selected assistant or public tool records stay verbatim, supporting records can be summarized, and all reviewed records remain in a recoverable archive. This is opt-in, not the default attachment behavior." width="880">
</p>

The complete reviewed archive remains recoverable. The current agent can select context; using another agent requires delegation permission.

<details>
<summary><strong>Transfer rules and implementation details</strong></summary>

The controller resolves source IDs and delegates to source-specific readers. Native creation uses separate provider adapters. T3 IDs may expose a verified nested native source, but T3 attachment and provider boundaries remain distinct. The source provider is never inferred from the receiving agent.

Direct mode is admitted only when reviewed public-history coverage is complete and its entire serialized packet fits a 24,000-character transfer budget. The limit is not a model context-window claim. Partial or oversized history returns `native_required`; unsafe or invalid input fails closed. History is never silently truncated.

Fresh-context workflows accept reviewed `user`, `assistant`, and public `tool` records. The snapshot supplies the stable-ID schema. Source logs and app state are read-only. Pattern-based screening withholds entire secret-like tool records, identifies their omissions, and keeps safe history usable. User/assistant matches still stop export. Screening is not a guarantee of recognizing every secret; native provider-local forks are not sanitized exports.

See the [workflow](skills/fork/references/workflow.md) and [direct-context contract](skills/fork/references/direct.md) for exact behavior.

</details>

## What we test

Automated checks cover source resolution, completed-turn boundaries, public tool evidence, frozen snapshots, secret-like record withholding, and explicit failure handling.

Opt-in runtime tests create actual Codex and Claude child sessions from synthetic histories. They check that the child is separate, the source is unchanged, and unfinished later turns are excluded. T3 adapter tests use synthetic databases; they do not test creating threads in the T3 UI.

These checks verify behavior, not better model answers, lower costs, or greater speed. The [historical benchmark](docs/historical-benchmark.md) is preserved separately and does not measure the current controller.

## Honest limits

- **Attachment is not a lossless clone.** It transfers supported public history, not hidden reasoning or attachment bytes. Missing or unsupported content is disclosed.
- **Separate conversations can share files.** Better Fork does not create worktrees or restore historical file contents.
- **Native children are provider sessions.** They do not automatically appear as new T3 UI threads. A T3 provider mapping may cover only the latest backend session after a restart.
- **History must be accessible locally.** Installing the skill on another computer does not synchronize conversations.
- **Dynamic and direct modes are experimental.** They prepare context, not a new session, and do not guarantee better output.

## Repository

```text
skills/fork/
├── SKILL.md
├── package.json              # Optional Claude native SDK
├── references/
│   ├── direct.md
│   └── workflow.md
└── scripts/
    ├── better_fork.py        # Shared controller
    ├── history_adapters.py  # Native public projections
    ├── native_fork.py       # Native execution adapters
    ├── claude_native.mjs    # Official SDK bridge
    ├── direct_context.py
    ├── fork_context.py
    ├── read_history.py
    ├── resolve_session.py
    └── test_*.py
```

The Python controller uses only the standard library. Only Claude native creation needs the optional Node SDK. Better Fork does not replace a client's built-in `/fork` command.

Run the automated checks with `python3 -m unittest discover -s skills/fork/scripts -p 'test_*.py'`. Model-free provider runtime smoke tests are opt-in with `BETTER_FORK_RUN_NATIVE_SMOKE=1`; they use synthetic conversations in temporary stores, not your real chats.
