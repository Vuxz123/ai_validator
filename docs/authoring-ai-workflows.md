# Authoring AI Workflows

Create a `.yaml` file under your workflow directory. No Python change is needed to
add a source-review objective supported by the existing Git/context tools.

```yaml
id: custom_reward
version: 1
triggers:
  source_groups: [ads]
checks:
  - id: CUSTOM_REWARD_001
    executor: agent
    severity: high
    objective: Reward is granted only once after a successful ad result.
    instructions:
      - Trace ad entry points through callbacks to the reward mutation.
      - Inspect failure, cancellation and duplicate callback paths.
      - Establish a concrete caller and inspect platform guards.
    context_requests:
      - Full reward method and callback implementations.
      - Relevant caller implementations if reachability is unresolved.
    verdicts:
      pass: Source proves success gating and duplicate prevention.
      fail: A reachable path grants reward early or more than once.
      unknown: Callback or caller implementation is unavailable.
    evidence_required:
      - Target file, line, caller path and guards supporting the conclusion.
```

Map `ads` in project config. Include `custom_reward` in `rule_packs` if that list
is configured. The ID is the YAML workflow ID, not its filename. Pass the containing
directory via `--workflows` to preview/order/analyze. The directory contains the
entire selected workflow library; a custom directory does not merge with defaults.

`objective`, `instructions`, `context_requests`, and `verdicts` are delivered to the
agent as guidance. Verdicts require pass/fail/unknown and optionally not_applicable.
`context` defaults to `[changed_code, diff]` for checks using objective. Legacy
description/context workflows remain supported. Deterministic checks cannot use AI
guidance fields. Increment version when changing a check's meaning.

Context requests are natural-language evidence goals, not executable tool calls.
The agent names missing files/types in its UNKNOWN summary/limitations; the existing
engine attempts one bounded expansion from known paths and caller candidates. This
does not implement arbitrary MCP queries, unlimited browsing, or Unity runtime tests.
Missing source remains UNKNOWN; YAML cannot bypass verification or turn errors into PASS.

## Editable evaluation cases

Each file under `examples/checklist_cases/` contains `id`, `project`, `files` and
`expected`. `files` maps Git-relative paths to literal source text (`|`); `project`
uses the same source-group config as production. `expected` maps check IDs to status.
The harness creates neutral baseline placeholders and target source commits.
Expectations remain outside Git and are not sent to the agent.

For a synthetic case with a defined caller scenario, add an optional execution
premise to the case YAML (not the production workflow or project config):

```yaml
execution:
  entrypoint: Scenario.Run
  assumption: Called once in this synthetic scenario.
```

The evaluation harness supplies this to both review and verify. The agent need not
find another caller above that entrypoint, but must still prove the downstream path
from its source. This does not execute C# or force a verdict. Reports are marked
`assessment_scope: synthetic_fixture`; the assumption is retained in context.
Production CLI analysis does not expose this option and keeps normal reachability
requirements. Expected labels remain hidden. Cases with missing implementations can
still return UNKNOWN under an execution premise.

Copy any sample, change its ID/source/expectations and run:

```powershell
$eval = & $py examples/evaluate_checklists.py --cases-dir .\my-cases --workflows .\my-workflows --backend codex --case my_case | ConvertFrom-Json -ErrorAction Stop
$eval.cases.checks | Format-Table check_id,expected,actual,verified,matched -Wrap
```

Use `--prepare-only` instead of `--backend codex` to avoid model calls. Add cases
without editing Python. Do not put expected verdicts into fixture source/comments.
Changing labels does not improve accuracy: inspect mismatched reports before revising
the fixture or instructions. These fixtures assess source reasoning, not Unity execution.
