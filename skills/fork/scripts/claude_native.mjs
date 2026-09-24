// Optional Claude SDK adapter. Imports no T3 code and never calls query().
import { pathToFileURL } from "node:url";

let sdk;
let dispatched = false;
let childId;
try {
  const sdkPath = process.argv[2];
  try {
    sdk = await import(sdkPath ? pathToFileURL(sdkPath).href : "@anthropic-ai/claude-agent-sdk");
  } catch {
    process.stdout.write(JSON.stringify({ ok: false, error: "claude_sdk_unavailable" }));
    process.exit(2);
  }
  if (typeof sdk.forkSession !== "function" || typeof sdk.getSessionMessages !== "function") {
    process.stdout.write(JSON.stringify({ ok: false, error: "claude_sdk_fork_unsupported" }));
    process.exit(2);
  }
  let input = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) {
    input += chunk;
    if (input.length > 65536) throw new Error("request too large");
  }
  const request = JSON.parse(input);
  const options = request.cwd ? { dir: request.cwd } : {};
  const messages = await sdk.getSessionMessages(request.session_id, options);
  if (!messages.length) {
    process.stdout.write(JSON.stringify({ ok: false, error: "claude_source_unavailable" }));
    process.exit(2);
  }
  if (!messages.some(message => message.uuid === request.through_turn)) {
    process.stdout.write(JSON.stringify({ ok: false, error: "claude_boundary_unavailable" }));
    process.exit(2);
  }
  dispatched = true;
  const child = await sdk.forkSession(request.session_id, { ...options, upToMessageId: request.through_turn });
  childId = child.sessionId;
  const copied = await sdk.getSessionMessages(child.sessionId, options);
  process.stdout.write(JSON.stringify({ ok: true, session_id: child.sessionId, persisted: copied.length > 0 }));
} catch {
  // Never echo provider exceptions: they can contain transcript text or credentials.
  process.stdout.write(JSON.stringify({ ok: false, session_id: childId, error: dispatched ? "claude_fork_result_unknown" : "claude_source_unavailable" }));
  process.exitCode = 2;
}
