# Repository Guidelines

## Project Structure & Module Organization

This Python POC analyzes Unity/C# build changes locally. `validator/` contains the CLI, SQLite lifecycle store, Git reader, YAML loader, agent adapter, runner, and deterministic texture checks. `workflows/` holds common, rewarded-ad, Unity lifecycle, and texture metadata checklists. `tests/` contains integration tests and labeled fake agents. `examples/` provides a demo and PowerShell build wrapper.

`unity_snapshot.py` exports committed text; `unity_index.py` streams full Assets/Packages into SQLite; `unity_mcp.py` queries bounded projections through UnityGraph MCP. `workflows/code_impact.yaml` assesses C# impact. `index-unity` prewarms a SHA cache without ordering or confirming a build.

Read `README.md` for current behavior. `AI_Build_Change_Validator_Unity_CSharp.docx` describes broader future architecture; current requirements use independent analysis without a build gate. Design notes are under `docs/superpowers/`.

## Build, Test, and Development Commands

`validator/project.py` loads generic project mappings and explains routing. `--project-config` enables logical source groups and pack selection; `preview` reads endpoint paths without model calls or database mutations. Config/root normalization does not require UnityGraph. Preserve legacy routing when no config is supplied and report missing enabled mappings explicitly.

Run from the repository root on Windows:

- `py -3 -m venv .venv`: create the Python environment.
- `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`: install PyYAML.
- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`: run tests.
- `.\.venv\Scripts\python.exe examples/demo.py`: generate retained sample reports.
- `.\.venv\Scripts\python.exe -m validator --help`: inspect CLI commands.

No Unity build runs here. Tests create temporary Git repositories.
Install `requirements-unitygraph.txt` for optional local MCP tests; enable retrieval with `--unity-project`. Never use a mutable Editor graph for a frozen build.

## Coding Style & Naming Conventions

AI workflow semantics belong in YAML (`objective`, `instructions`, `context_requests`, `verdicts`), not custom Python executors. Editable evaluation fixtures live in `examples/checklist_cases/*.yaml`; keep expected labels outside model context. Context requests are guidance for bounded source retrieval, not arbitrary commands.

Use four spaces, Python `snake_case` functions/fields, and `PascalCase` classes. Keep lifecycle, retrieval, and agent execution separate. Built-in CLI transports live in `validator/backends.py`; preserve argv execution without a shell. No formatter or linter is configured. Workflow IDs use lowercase underscores; check IDs use uppercase underscores. Increment workflow versions when rules change.

## Testing Guidelines

Add behavior-focused unittest `test_*.py` cases for baselines, routing, snapshots, and agent failures. Assert observable reports and database state. Fixture-agent results do not establish AI accuracy. Live `examples/smoke_backend.py` calls consume provider usage; ordinary tests are offline. Windows timeout tests need permission to terminate their own child processes. No coverage percentage is mandated.

## Commit & Pull Request Guidelines

No Git history was available when this guide was written. Use imperative subjects, such as `Fix rename workflow selection`. Describe behavior changes, validation results, limitations, and relevant issues in PRs.

## Architecture Guardrails

Open code impact uses `validator/investigation.py`: bounded agent requests for frozen reads, symbol search and UnityGraph, then independent per-finding verification. Keep baseline source separate from target evidence. Tool errors/round caps must remain visible. Do not expose shell execution to the investigation protocol.

Freeze baseline/target at order time; compare endpoint trees with `git diff baseline target`. Only explicit confirm advances a branch/profile baseline; older orders cannot rewind it. Agent failures yield UNKNOWN, never PASS. Keep analysis independent of build success. Do not commit `.validator/`, credentials, or source-bearing reports. External agent commands are trusted local configuration, not a sandbox.
