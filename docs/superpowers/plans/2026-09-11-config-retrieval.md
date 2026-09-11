# Frozen Unity Configuration Retrieval

Approved scope: read committed Unity configuration and XML during open investigation.
Allow Assets/Packages XML and ProjectSettings .asset/.txt/.xml within the configured
Unity prefix. Keep Graph script-only and all existing byte/deadline limits.
Before reading, resolve an exact literal Git tree path. Missing files must report
absence from that snapshot, without claiming generation or falling back to disk.
Agent must name the concrete configuration mismatch hypothesis; truncated diff alone
is coverage, not a defect. Build-generated content needs generator/build evidence.

Implementation sequence:
1. Add regression tests for nested frozen settings/XML, missing files and blocked roots.
2. Run investigation tests to observe missing capability.
3. Extend retrieval path/format checks and exact snapshot existence diagnostics.
4. Update agent guidance and workflow version; run investigation/source-window tests.
