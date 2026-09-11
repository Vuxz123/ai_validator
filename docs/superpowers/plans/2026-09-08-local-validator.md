# Local Validator Implementation Plan

**Goal:** Runnable local order/confirm lifecycle and YAML-driven analysis with tests.
**Architecture:** SQLite store, immutable Git reader, strict workflow loader, bounded
runner, and CLI with detached worker. Implement inline in the existing non-Git folder.
**Tech stack:** Python 3.11+, PyYAML, sqlite3, unittest, Git CLI.

- [x] Write CLI integration tests using temporary Git repositories. Check frozen
  baselines, failed/unconfirmed builds, profile isolation, idempotency, and late confirmation.
- [x] Run `.venv/Scripts/python -m unittest discover -s tests -v`; observe missing CLI.
- [x] Implement `validator/store.py`, `git.py`, and `__main__.py` for lifecycle.
- [x] Add failing analysis tests for YAML routing, first build, disabled agent,
  invalid configuration, immutable snapshots, invalid evidence, and verifier rejection.
- [x] Implement `workflows.py`, `runner.py`, `agent.py` and example YAML files.
- [x] Verify external adapter with a clearly labeled deterministic fixture executable;
  verify detached worker and real CLI demo without claiming AI/Unity validation.
- [x] Document installation, local pipeline integration, adapter protocol, workflow
  extension, recovery, and limitations. Update AGENTS.md to match actual implementation.
- [x] Run the full integration suite and inspect demo reports before delivery.
