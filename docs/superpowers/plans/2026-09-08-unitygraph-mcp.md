# UnityGraph MCP Implementation Plan

**Goal:** Supply SHA-bound UnityGraph MCP context to advisory analysis.

**Architecture:** An opt-in `--unity-project` identifies the Unity directory within
the ordered repository. A bounded subprocess exports committed text, builds or
reuses a versioned graph cache, and calls the official stdio MCP server. The runner
adds graph hints and snapshot text matches to agent context; graph failure records
incompleteness and never advances confirmation or blocks the build.

**Tech stack:** Python, Git objects, UnityGraph 2.1.4, MCP Python client, unittest.

User approved this architecture and implementation in the current conversation.
No Git repository exists here, so no worktree or commit is created.

- [x] Add tests for snapshot export/cache integrity, actual MCP queries, missing
  singleton caller fallback, nested Unity paths, failure and worker forwarding.
- [x] Implement `validator/unity_snapshot.py`: allowlisted text export by object
  ID, 32 MiB budget, 4 MiB file cap; cache keyed by repo, prefix, SHA, schema/version.
  Publish completed manifests atomically; never use a partially built cache.
- [x] Implement `validator/unity_mcp.py`: isolated official MCP server, exact node
  ID `get_neighbors` queries (one hop), response/context caps, bounded cleanup.
  Treat graph edges as unverified hints, and search committed C# for seed names.
- [x] Wire CLI and detached worker options. Normalize only workflow selection
  paths; retain Git-relative source/evidence paths. Adapt texture collector prefix.
- [x] Add a generic C# impact checklist and attach bounded related target files;
  deletions query baseline too. Baseline text cannot substantiate target evidence.
- [x] Run targeted tests, full offline suite, and actual local StuffSort MCP smoke.
  Document commands, limits, cache provenance, and advisory behavior.

Verification: 49 unittest tests passed in 80.454 seconds; pip check passed.
Official local MCP smoke on StuffSort SHA 70672a4b: 46.47 seconds first build,
6.83 seconds cached. Singleton source retrieval includes GameManager/HomeManager.
Independent review found two context bugs, both reproduced and fixed with tests.
Windows is the verified target; POSIX hard-timeout descendant cleanup remains
unverified and is documented. No Unity compilation or live model review performed.
