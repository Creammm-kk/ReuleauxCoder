# Runtime protocol v1

The linear CLI and React TUI are clients of a backend-owned session. They render events,
collect input and manage focus. The backend owns the agent, command registry,
turn workers, deferred commands, steering, stop state, approvals and persistence.
All built-in slash actions and panel actions pass through the same CommandService.

## Layers

```
CLI / TUI / editor adapter
         RuntimeClient
         RpcPeer
         MessageTransport (memory or stdio)
         RpcPeer
         RuntimeServer
         CommandService + Agent
```

`MessageTransport` has just `send(str)`, `receive() -> str | None`, and `close()`.
`RpcPeer` owns JSON-RPC IDs, pending replies, method dispatch and ordered
notifications. A reader thread always remains available while handlers run on
workers, including while the backend asks the frontend for human input. Runtime
execution has its own workers; submitting a turn returns admission immediately.
Existing synchronous agent and interaction code therefore requires no async rewrite.

Local CLI/TUI use two memory channels, including JSON encoding/decoding. There is
no direct-call fast path. The stdio process uses the same server and client contracts:

```sh
rcoder --rpc-stdio --config /path/to/config.yaml
```

Stdio frames are compact UTF-8 JSON documents terminated by LF (maximum 16 MiB).
Newlines inside JSON strings are escaped. Stdout carries only protocol frames;
startup output and diagnostics go to stderr. This is newline framing, not LSP
Content-Length framing. No TCP listener, HTTP server, or WebSocket dependency is
needed for this entry point.

In VS Code Remote, a workspace extension can launch this process in the remote
workspace and exchange stdio frames there. The editor adapter owns the connection
to its local UI. A future socket/WebSocket transport can implement MessageTransport;
authentication and connection ownership would belong to that adapter. The existing
Go tool-execution peer and its relay protocol are a separate service.

## Messages

All envelopes use JSON-RPC 2.0. Requests have IDs, notifications have no ID, and
responses contain either `result` or `error`. Request parameters are objects.
The Python peer also accepts positional parameters and incoming request batches;
the React frontend uses object parameters and individual messages.

| Method | Direction | Parameters / result |
| --- | --- | --- |
| `initialize` | client request | `{version: 1, profile}` → version, metadata catalog, state, startup events, recent conversation, plan/progress, history path and base URL |
| `runtime.submit` | client request | `{value}` with text or ActionRequest → Submission(status, state) |
| `runtime.snapshot` | client request | `{}` → RuntimeSnapshot |
| `runtime.interrupt` | client request | `{}` → outcome and discarded steering count |
| `runtime.resize` | client notification | `{rows, columns}`; backend adds the owning agent/session/generation |
| `view.panel` | client request | `{payload}` with ViewEventPayload → PanelPresentation or null |
| `runtime.report_issue` | client request | phase, error_type, ref, optional count and event routing fields → recorded runtime issue |
| `runtime.record_performance` | client notification | category, name, elapsed_ms, optional status and scalar attributes; feeds the backend performance view |
| `runtime.shutdown` | client request | `{}` → saved session ID or null; stops, cancels interactions, waits and saves once |
| `interaction.request` | backend request | `{kind, request, timeout_seconds}` → the corresponding typed response |
| `interaction.cancel` | backend notification | `{request_id}` |
| `runtime.event` | backend notification | `{event, session_generation}` with UIEvent; generation scopes command views as well as runtime facts |
| `runtime.state` | backend notification | `{state}` with RuntimeSnapshot |
| `runtime.command` | backend notification | `{text}` for the submitted slash text |
| `runtime.completed` | backend notification | `{result}` with CommandResult |
| `runtime.failed` | backend notification | `{error_type, message}` after the failure has been logged |

Initialize once before submitting. Admission status is `running`, `queued`,
`steering`, or `rejected`; it is not an execution result. Completed/failed
notifications precede the operation's idle state notification. Snapshots carry
monotonically increasing revisions so a late response cannot overwrite newer
state. Frontends must not infer command queue policy from command names.

The independent `reuleauxcoder-tui/` React frontend groups catalog triggers into
top-level slash menus. `ActionDescription.parameters` contains primitive form
fields derived from each command dataclass; `preview` explicitly marks safe
menu previews. Actual panel rows still come from `view.panel`. Tool outcomes,
including diffs, diagnostics, retention metadata and archive references, are
public codec records. Runtime snapshots include the live `approval_waiting`
count. Event generation must be applied before restoring command-view history,
so a later state snapshot cannot clear the newly restored transcript.

## Data encoding

`app/rpc/codec.py` is the single record/enum catalog. Contracts use stable short
type names; the decoder never imports an incoming module name. The representation is:

```json
{"$type":"ActionRequest","fields":{"action_id":"thinking.set_effort","command":{"level":"high"}}}
```

Records use `$type` plus `fields`; enums use `$type` plus `value`; tuples and
frozensets use `$type` plus `items`. Lists and primitives are ordinary JSON.
User dictionaries containing a `$type` key are escaped as
`{"$type":"dict","items":{...}}`, so user content cannot become a contract.
Command parameters are plain objects: only the backend resolves their action ID
and constructs the registered command parameter dataclass. Handler callables and
agent objects cannot cross this boundary. Breaking contract changes require a
protocol version change, rather than a parallel compatibility dispatch path.

An initialization profile is a UIProfile record containing `ui_id`, `display_name`
and a frozenset of UICapability enums. Interaction kinds are `confirm`, `choose_one`,
`input_text`, and `review`. Both sides preserve each interaction's request ID.
Monotonic deadlines are converted to remaining seconds and rebased at the frontend;
absolute monotonic timestamps never cross processes.

## Lifecycle and failure policy

One connection owns one backend session. EOF closes the stdio backend; its owner
stops work and saves through the same shutdown path as local CLI/TUI. Shutdown is
idempotent and waits up to ten seconds for cooperative operations to stop. Failure
to stop or save is surfaced. There is no automatic reconnect or replay of mutating
requests; reopening uses the normal persisted-session restore path.

Method/parameter/protocol errors use JSON-RPC error codes. Unexpected handler
failures log a traceback and return an error. Runtime failures preserve conversation
content, emit a UI error and notify the client. CLI waiters receive the failure;
TUI can render it and accept another submission. Connection loss releases pending
RPC requests and cancels frontend interactions. Content is persisted by the
existing session ledger and configured exit-save policy, not by the transport.

The append-only frontend pumps interaction prompts on its foreground thread;
TUI prompts use their existing focus coordinator. Frontend tests cover rendering
and input forwarding. Backend/protocol tests cover queue policy, interruptions,
reverse requests, framing, errors, shutdown and a real stdio subprocess.
