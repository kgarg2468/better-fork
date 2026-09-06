# Context-transfer evaluation

Read only to design or interpret an experiment. Current evidence does not establish universal superiority for any continuation method. A small v4 development benchmark had 24/24 passing assignments. Direct versus native was about 9% faster with 11% more input for Codex; for Claude it was about 26% faster with 2.3% lower estimated cost and 29% more input. Treat these as experiment-specific observations, not a default change or general performance claim. Preserve explicitly requested models.

## Arms and controls

Predeclare three arms:

1. Native fork with the host's full cached context.
2. Fresh receiver with the explicitly selected legacy selector packet.
3. Fresh receiver with the explicitly selected model-free direct packet.

Hold receiver model, tools, compute budget, repository checkpoint, next-task prompt, and environment constant. Capture native full cached-context accounting rather than treating cached tokens as free. Never substitute models.

Use held-out historical sessions as the sampling unit, covering ordinary continuation and changed-direction tasks. Repeat at session level and keep a session's variants from crossing tuning and evaluation partitions.

Do not export or inject grader internals, solutions, hidden tests, future turns, private reasoning, system text, or raw unreviewed exports into fresh-context arms. A native host fork may retain provider-private context internally; do not expose it or treat it as reviewed public history. Record partial history and fallback as treatment behavior, not exclusions.

## Analysis

Predeclare the primary quality metric and noninferiority margin. Test each fresh-context method against native first; only then compare cost, token use, and latency.

Analyze intention-to-treat. Launch, selection, retrieval, packet, and fallback failures stay in their assigned arms. Include preparation, selector, transfer, receiver, retrieval, fallback, cached-context, and failed-attempt tokens, cost, and latency.

Report session-level uncertainty, failure categories, contamination checks, and redirect sensitivity. Fewer visible prompt tokens are not a win if cached context, preparation, retrieval, fallback, or failures reverse the total.

Do not start live calls here. A run needs separate authorization, a frozen protocol, leak review, and admitted source/receiver isolation.
