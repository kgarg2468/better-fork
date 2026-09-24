# Historical benchmark

[Back to the README](../README.md)

This historical development comparison tested native, the older selector workflow, and direct context. It did **not** measure the current portable controller, richer attachment, native adapters, or small-model reliability. It is not evidence that these changes outperform native forking.

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

<details>
<summary><strong>Full paired results and benchmark protocol</strong></summary>

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

</details>

## Limitations of this comparison

This benchmark supports one bounded conclusion: **direct context is a promising fast path for short, complete, changed-direction histories.** It does not prove that Better Fork is generally better than native Codex or Claude Code forking.

- There were only two independent task families; repeats are not new independent samples.
- These were known development cases, not held-out natural coding sessions or long histories.
- Direct used more input tokens than native on both providers.
- One of four Codex pairs was slower with direct context.
- Native can retain provider-private state and cached context that a reviewed public projection cannot reproduce.
- All outputs passed these graders, but no architecture can guarantee agent output quality.
- Recovery was available but not invoked by these tasks, so successful recovery behavior was not established by the live comparison.
