# Full-project index implementation plan

User approved expanding indexing while retaining bounded agent context.

- [x] Test export beyond the former 32 MiB/4 MiB limits and embedded Packages.
- [x] Build a SQLite index from all supported committed Assets/Packages text and
  MonoManager execution order. Parse scripts globally, then ingest serialized
  assets individually through pinned UnityGraph parsers. Store nodes/edges on disk.
- [x] Preserve cross-file GUID and prefab variant resolution with global maps.
- [x] Extract bounded one-hop query graphs from SQLite for the official MCP server.
  Keep full-index SHA/hash validation and independent small retrieval budgets.
- [x] Make full indexing the default, retain explicit graph roots for scoped runs,
  and add a standalone prewarm CLI for long first indexes.
- [x] Test caches, package routing, cross-asset relations, coverage and failure;
  run actual StuffSort full-index smoke and offline suite. Document parser limits,
  unresolved registry packages and binary assets; never claim semantic completeness.

No Git repository exists in this workspace; no commit/worktree is created.

Validation: 57 tests passed in 96.440 seconds; pip check passed. Independent review
found three P2 issues (directory filtering, shader references, oversized seeds),
all reproduced and fixed. Final schema-3 StuffSort index parsed 1,321 C# files,
1,981 prefabs, 94 scenes, 42 controllers and five ShaderGraphs; 12,425 text/meta
files exported, zero budget omissions. 29 duplicate-node warnings remain upstream.
Index build took 490.288 seconds under concurrent local test load. Official MCP
queries for AdController against cached target/baseline (same SHA for smoke reuse)
plus related caller retrieval took 4.8 seconds. No model or Unity build invoked.
