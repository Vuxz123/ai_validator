# Local validator POC

The approved conversation design is a fixed local workflow with declarative YAML
checklists. Analysis runs alongside a local build and never controls its outcome.
Python CLI and SQLite provide a small standalone implementation for Unity/C# repos.

`order` resolves an explicit target commit, freezes the last confirmed commit for
repository/branch/profile, stores a UUID build ID, and normally launches a detached
analysis worker. The pipeline must build the returned target SHA. `confirm` is an
independent, explicit assertion by the caller that the build succeeded. It is
idempotent and cannot move a baseline behind a newer confirmed order.

Analysis reads Git objects, never mutable working-tree source. It compares endpoint
trees, selects common and path-based YAML checklists, creates bounded context, and
executes deterministic or external-agent checks. The initial context contains a
diff and changed text files only; graph traversal is explicitly unavailable.
Missing provider/context yields UNKNOWN. Findings require valid target-file evidence
and a separate verification invocation before being marked verified. AI output is
untrusted data. Analysis status and findings are separate from build confirmation.

An external agent adapter is an argv JSON array, run without a shell, accepting a
JSON request on stdin and returning JSON on stdout. It is optional; no credentials
or provider are assumed. This adapter is trusted executable configuration, not a
sandbox. Budgets limit file/context size and per-call runtime. The POC does not run
Unity or allow model-selected shell commands.

Reports and their context/checklist inputs are retained in SQLite. First build gets NO_BASELINE, not PASS.
Order retries can reuse an explicit ID. Failed/crashed workers can be retried
explicitly once the prior process is stopped. No service, graph database, automatic
test generation, or cross-build finding lifecycle is included in this POC.
