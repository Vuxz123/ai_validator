# Checklist Evaluation

Implemented six retained synthetic Git cases: Ads and UI, each with good, bad and
unresolved source. Ads contributes two checks per case, UI one: nine labels total.
Run the real runner with only the matching workflow pack and common snapshot check.
Keep labels outside the repository and use opaque repo directories so expected
answers cannot leak through build paths. Never place expectations in agent requests.

Scoring requires the expected status and COMPLETED execution; FAIL also requires
verified=true. Errors, timeouts and missing checks are mismatches, even for UNKNOWN
labels. A mismatch produces exit code 1 and retained reports. Prepare-only never calls
a model. Each case uses an independent SQLite store and synthetic confirmed baseline;
the analyzed target stays unconfirmed. No real game files are touched.

The good/bad sources include a concrete local caller scenario. Unknown sources refer
to unavailable external dependencies intentionally. These are source-review fixtures,
not compilable Unity projects or runtime tests. Synthetic results are not a production
accuracy measurement. Unit tests use an explicitly fake adapter only to verify routing
and orchestration; live backend results must be measured separately.

Execution scope update: good/bad case YAML declares `Scenario.Run` called once.
Harness passes this separately as `fixture_execution` to review/verify; source still
must establish the downstream defect. No caller above the assumed entrypoint is
required for synthetic assessment. Production CLI has no such override. Reports
label the synthetic scope explicitly. Expected statuses are unchanged.
