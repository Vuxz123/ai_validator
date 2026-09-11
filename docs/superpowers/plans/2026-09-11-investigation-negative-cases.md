# Investigation False-Positive Cases

Approved extension: caller guards, unreachable private code, preexisting defects and
same-name types in separate namespaces. Four additional YAML fixtures reuse the
existing evaluator without changing model policy or scoring thresholds.

Each fixture supplies a neutral closed-program execution premise. Source proves the
guard, absence of a private call, unchanged failing path, or explicit namespace alias.
Expected PASS means no new reachable defect attributable to the delta in that scope.
The preexisting-defect program still throws; the delta adds only an unused constant.

Tests prepare real Git baselines/targets and compare every committed fixture source,
including unchanged caller files. Existing routing and rubric-isolation tests iterate
all eight cases. Offline tests do not establish model accuracy; run the four new case
IDs with the live backend and inspect unexpected FAIL/UNKNOWN reports.
