# Full-project UnityGraph index

Verified on StuffSort3d commit `70672a4b5f4696ff7f47e30110e88d7315f1322c`.

The default index now covers supported committed text under both Assets and
embedded Packages. It parses scripts globally, serialized assets individually,
and stores structural nodes/edges in SQLite. MCP receives only a bounded projection.

## Observed result

| Item | Count |
| --- | ---: |
| Exported text/meta/config files | 12,425 |
| Exported bytes | 611,067,057 |
| C# files parsed | 1,321 |
| Prefabs | 1,981 |
| Scenes | 94 |
| Animator controllers | 42 |
| ShaderGraphs | 5 |
| Nodes / edges | 36,620 / 131,156 |
| Budget omissions | 0 |
| Duplicate-node warnings | 29 |

The final schema-3 build took 490.288 seconds while other local checks ran.
Cached AdController MCP queries for target/baseline plus caller source retrieval
took 4.8 seconds. Both smoke snapshots intentionally used the same SHA to verify
cache reuse; this was not a real build-delta review. Retrieved source includes
GameManager and HomeManager. Model accuracy and Unity runtime behavior were not tested.

Manifest: `.validator/unitygraph-cache/ba3c89cf85d5ec9901ab3c83be98a50e325fc78560effe96e4901b6937a93742/snapshot.json`.
MCP artifact: `.validator/full-index-mcp-smoke.json`.

## Use

```powershell
.\.venv\Scripts\python.exe -m validator index-unity --repo C:/Users/DPC00176/RiderProjects/stuff-sort/StuffSort3d --target HEAD
```

Use the same database path, graph roots and exact SHA as analysis. Existing graph
root overrides still narrow scope; omit them to index Assets and Packages.
Prewarm both baseline and target when needed. Indexing does not order or confirm
a build. Alternatively allow the order worker more time with
`--unity-project <project> --graph-timeout 600 --budget 1800`.

## Limits

Full supported-file indexing is not complete semantic understanding. Registry
packages without committed sources, binary/LFS payloads, general ScriptableObject
assets, materials and other unsupported formats are not resolved. Inspector
payloads are retrieved from source rather than stored in the structural index.
UnityGraph name-collision and singleton limitations still apply. The manifest
records unsupported extensions and parser warnings. Cache reuse is per SHA;
incremental indexing across different commits is not implemented.
