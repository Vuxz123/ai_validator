# Open Investigation Evaluation

User-approved scope: synthetic project bug, SDK bug, clean delta and missing-context
cases for the existing open investigation executor. No per-case workflow instructions.

Fixtures are editable YAML under examples/investigation_cases. Baseline files are
committed first; target files overlay them in a second commit. A neutral execution
premise establishes a synthetic entry point. Expected status, evidence anchors,
ownership and mechanism terms remain outside Git/model requests.

Scoring requires a normal completed investigation and one-to-one matching of verified
findings to expected anchors/ownership/summary terms. Extra findings, timeout, tool
errors and round caps cannot count as success. Summary terms are a transparent lexical
rubric, not proof of semantic equivalence; retained reports need human inspection.

Implemented and tested: loader validation, frozen fixture preparation, rubric isolation,
independent verification wiring, ownership scoring, duplicate/unrelated finding rejection
and operational UNKNOWN rejection. Prepare-only creates four isolated fixture databases.
Live Codex/OpenCode accuracy is measured separately; offline adapters do not establish it.
