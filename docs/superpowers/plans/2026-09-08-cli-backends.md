# Codex and OpenCode backend plan

Approved scope: wire both installed CLIs into the fixed review/verify pipeline.
Keep custom argv adapters compatible. Built-in backends receive only frozen context
in a temporary directory; Codex uses read-only sandbox and a strict output schema,
OpenCode a dedicated agent denying tools and automatic sharing. This is context-only
analysis, not full repository traversal. Model override is optional and no auth
tokens are read/copied by validator.

- [x] Write failing tests for review/verify, CLI flags, JSONL parsing, error events,
  executable resolution, and worker option forwarding.
- [x] Implement backend execution with bounded logs, per-call timeout/process-tree
  cleanup, schema generation, and Windows npm launcher resolution without a shell.
- [x] Wire CLI/PowerShell options and report backend/model provenance.
- [x] Run offline tests, then bounded live smoke requests on synthetic data; document
  unavailable authentication/provider separately from protocol test results.
- [x] Update README and review changes before final full verification.
