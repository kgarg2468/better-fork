<h1 align="center">Better Fork</h1>

<p align="center">
  <strong>Fork the work, not every token.</strong>
</p>

<p align="center">
  A native-first <code>/fork</code> skill with an opt-in, lossless direct-context fast path.<br>
  Built for Codex and Claude Code. No proxy, service, account, or API key.
</p>

<p align="center">
  <a href="#install"><img src="https://img.shields.io/badge/install-one_command-blue" alt="One-command install"></a>
  <a href="#benchmark"><img src="https://img.shields.io/badge/benchmark-24%2F24_pass-brightgreen" alt="24 of 24 benchmark attempts passed"></a>
  <a href="#honest-limits"><img src="https://img.shields.io/badge/claims-bounded-orange" alt="Bounded claims"></a>
</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#benchmark">Benchmark</a> ·
  <a href="#honest-limits">Honest limits</a>
</p>

---

## Why

Most forks should simply continue from the provider's native session. That is the default here.

The interesting case is a changed-direction fork: you want the new agent to inherit the useful public history, but you do not necessarily want to pay for a selector model or force it to read a context file before starting. Better Fork adds a deterministic direct-context route for that case.

```text
ordinary continuation ───────────────▶ native provider fork

explicit fresh-context redirect
  ├─ complete public history fits ───▶ direct packet, no selector call
  └─ partial or too large ───────────▶ native required, never truncate
```

## Install

Install the `fork` skill with the open skills installer:

```bash
npx skills add kgarg2468/better-fork --skill fork
```

In Codex, invoke it as `$fork`; `/fork` may be intercepted by the native client command. In Claude Code installations that expose skills as slash commands, use `/fork`.

You can also clone the repository and copy `skills/fork` into your agent's skills directory.

## How it works

`$fork ID` in a new chat now loads the previous conversation into that current
chat and keeps its selected model. IDs may come from T3, Claude, or Codex.
This is conversational context attachment; it does not merge backend session
identities. The history reader includes public user/assistant text and reports
that tool results and attachments are excluded. Separate native forks remain
available when explicitly requested. The benchmark below measures the earlier
context-transfer routes, not this attachment workflow.

Better Fork has three routes:

| Route | When it runs | Context behavior |
| --- | --- | --- |
| **Native** | Ordinary continuation; default | Uses the provider's native fork and cached/private session state |
| **Direct** | Explicit fresh-context opt-in | Injects every reviewed public record, exactly and in order; no selector or initial context-file read |
| **Legacy selector** | Explicit selector opt-in | Uses a model-selected compact packet plus a complete recoverable public archive |

Before choosing a route, the skill deterministically resolves the supplied ID. You can provide any of:

- a T3 thread ID;
- a native Claude Code session ID; or
- a native Codex session ID.

The read-only resolver maps T3 IDs to their actual provider-native session and returns the source cwd, model, completed boundary, and provider-specific launch arguments. It never assumes the source provider from whichever agent happens to be running the skill.

Direct mode is admitted only when reviewed public-history coverage is complete and its entire serialized packet fits a 24,000-character transfer budget. The limit is not a model context-window claim. Partial or oversized history returns `native_required`; unsafe or invalid input fails closed. History is never silently truncated.

Only reviewed `user`, `assistant`, and public `tool` records are transferable. System/developer text, hidden reasoning, private provider internals, secrets, and raw native exports are excluded.

## Benchmark

The fixed development comparison tested three routes—native, the older selector workflow, and Better Fork's direct workflow—on Codex and Claude Code.

| Provider | Native mean | Selector mean | Better Fork direct | Direct vs native | Direct input vs native | Direct cost vs native |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Codex | 118.6 s | 117.3 s | **108.0 s** | **8.9% faster** | 10.9% more | Unknown |
| Claude Code | 61.0 s | 68.8 s | **45.1 s** | **26.0% faster** | 28.7% more | **2.3% lower** |

All three routes passed all assigned coding and observed-workflow checks:

| Provider | Native | Selector | Direct |
| --- | ---: | ---: | ---: |
| Codex | 4/4 | 4/4 | 4/4 |
| Claude Code | 4/4 | 4/4 | 4/4 |
| **Total** | **8/8** | **8/8** | **8/8** |

### Full paired latency results

Best time in each row is bold. The slower Codex direct result is intentionally visible.

| Provider | Task family | Repeat | Native | Selector | Direct |
| --- | --- | ---: | ---: | ---: | ---: |
| Codex | Integer clock | 1 | 100.3 s | 110.1 s | **81.9 s** |
| Codex | Integer clock | 2 | 104.9 s | 108.3 s | **76.0 s** |
| Codex | Unicode CSV | 1 | 129.5 s | **110.2 s** | 139.1 s |
| Codex | Unicode CSV | 2 | 139.8 s | 140.6 s | **135.1 s** |
| Claude Code | Integer clock | 1 | 39.8 s | **32.0 s** | 37.7 s |
| Claude Code | Integer clock | 2 | 49.9 s | 51.2 s | **36.8 s** |
| Claude Code | Unicode CSV | 1 | 77.6 s | 78.4 s | **54.8 s** |
| Claude Code | Unicode CSV | 2 | 76.5 s | 113.7 s | **51.2 s** |

### Protocol

- Two previously observed development task families, repeated twice per route and provider.
- Twelve attempts and 28 model calls per provider; 24 attempts and 56 calls total.
- Two receiving turns per attempt from byte-identical repository checkpoints.
- Requested receivers: `gpt-5.6-sol` at low effort for Codex and `claude-opus-5[1m]` at low effort for Claude Code.
- Quality required both isolated coding-grader success and observed-workflow success.
- End-to-end wall time included deterministic preparation, selector calls where applicable, both receiver turns, and grading.
- Claude cost is the CLI's reported estimate, not an invoice. Codex supplied no cost estimate.

The direct route transferred every reviewed public record in all eight direct attempts, with no selector calls, truncations, integrity failures, or native fallbacks. The local implementation and benchmark plumbing passed 127 tests.

## Honest limits

This benchmark supports one bounded conclusion: **direct context is a promising fast path for short, complete, changed-direction histories.** It does not prove that Better Fork is generally better than native Codex or Claude Code forking.

- There were only two independent task families; repeats are not new independent samples.
- These were known development cases, not held-out natural coding sessions or long histories.
- Direct used more input tokens than native on both providers.
- One of four Codex pairs was slower with direct context.
- Native can retain provider-private state and cached context that a reviewed public projection cannot reproduce.
- All outputs passed these graders, but no architecture can guarantee agent output quality.
- Recovery was available but not invoked by these tasks, so successful recovery behavior was not established by the live comparison.

Native therefore stays the default. Direct mode is explicit and experimental; the legacy selector is still available only when explicitly requested.

## Repository

```text
skills/fork/
├── SKILL.md
├── references/
│   ├── direct.md
│   ├── evaluation.md
│   └── workflow.md
└── scripts/
    ├── direct_context.py
    ├── fork_context.py
    ├── resolve_session.py
    └── test_resolve_session.py
```

The helper scripts use only the Python standard library. Better Fork does not modify T3's fork UI or replace a client's built-in `/fork` command.
