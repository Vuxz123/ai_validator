# UnityGraph trial: StuffSort3d

Tested locally on 2026-09-08 with UnityGraph 2.1.4, against committed snapshot
`70672a4b5f4696ff7f47e30110e88d7315f1322c`.
Git root contains the Unity project under `StuffSort3d/`; working-tree edits were
not included. No Unity Editor, model call, or game-project write was performed.

## Results

- Initial 255 MiB export produced a 446 MiB graph, exceeding the reader's 128 MiB limit.
- Scoped export: 3,458 text files, under 32 MiB; `_Game`, `BravestarsSDK`, `ZeroX`.
- Build: 31,857 ms; 6,940 nodes; 63,093 edges; graph 58,343,344 bytes.
- 106 files omitted by budget; seven duplicate-node parser warnings.
- AdController neighborhood: eight edges (one attachment, three dependencies,
  four co-location relations). Co-location is not a call relationship.
- Offline validator suite: 36 tests passed. These test validator behavior, not
  Unity compilation or graph accuracy.

Artifacts: `.validator/unitygraph-probes/70672a4b-svo1w8dq/` contains graph,
SHA/hash manifest, parser report, exported snapshot, and related context.

## Evidence and accuracy gaps

`AdController.cs.meta` GUID matches `AdsConfigManager.prefab:83`, supporting the
attachment edge (graph site points to the component block at line 74).
`NewSDK/Reward.cs:64` calls `_controller.GetBestShowCandidate(Placement)`,
supporting an incoming dependency.

However, calls through `AdController.Instance` at
`_Game/Scripts/Common/Managers/GameManager.cs:60-61` and `HomeManager.cs:49`
are absent from this neighborhood despite the files being exported.
The `GetComponent<Reward>()` site at `AdController.cs:64` also resolves in the
graph to the namesake in `_Game/Scripts/GUI/RewardAnimation.cs`, rather than
the SDK Reward type. Treat type-name collisions as unresolved until checked
against namespace and source evidence.

## Integration decision

Use UnityGraph as supplementary context, with snapshot text search for singleton
callers and source verification of every relevant edge. Never infer safety from
an empty neighborhood. Preserve omissions and ambiguities in reports.

The initial probe was standalone. The subsequent MCP integration now provides
prefix normalization, context budgets, worker deadlines and baseline/target caches
through `analyze --unity-project`; see README for commands and remaining limits.

## MCP integration verification

The official stdio server was exercised on this same SHA with the scoped export.
Initial build plus target/baseline queries took 46.47 seconds; a repeat using both
cached snapshots took 6.83 seconds. These are local observations, not performance
guarantees. The smoke deliberately queried the same SHA twice to test reuse; it
did not compare a real build delta or confirm a build.

Supplementary committed-text retrieval included GameManager and HomeManager
source, covering the singleton callers the graph missed. The SDK/game Reward
collision remains an unverified graph hint and requires source/namespace review.
Artifact: `.validator/unitygraph-mcp-smoke.json`. No project source was sent to
Codex/OpenCode in this smoke; model quality is not established by MCP tests.
