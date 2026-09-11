# Generic Project Routing Implementation Plan

**Goal:** Reuse one validator and rule library across Unity repositories with different layouts.

**Architecture:** Keep immutable Git analysis and execution in the engine. Versioned workflow YAML files are the initial rule packs. A strict project config supplies the Git-relative Unity root, logical source groups, and enabled pack IDs. Routing returns explanations, missing mappings and matching paths. Ownership is annotation, never suppression of SDK findings.

**Tech stack:** Python, PyYAML, unittest, committed Git diffs. No Unity execution or paid model calls required for routing.

## Implementation

- [x] Add strict project config loader and ownership classification.
- [x] Add logical source-group triggers and shared explainable routing; preserve legacy CLI behavior without project config.
- [x] Add read-only `preview` and `--project-config` forwarding to order/analyze workers.
- [x] Record effective config/hash, workflow versions, routing and ownership in reports. Missing enabled mappings imply incomplete coverage.
- [x] Test identical checks on root/nested Unity layouts, missing mappings, disabled packs, invalid config and CLI integration.
- [x] Document generic setup, examples, commands and limitations.

## Decisions and limits

- Project patterns are Unity-relative; evidence remains Git-relative. `unity_root` works without enabling UnityGraph.
- `rule_packs` refers to existing workflow IDs; `common` is always included. No remote pack registry in this version.
- Config is trusted local input read at analysis time and embedded/hash-recorded in the report; it is not yet frozen in the order database. Retry must pass the same config for reproducibility.
- No config: retain historical Ads/UI mappings and label legacy routing. Explicit config: never silently fall back to those paths.
- `first_party`/`third_party` groups annotate evidence; overlap is `mixed`, missing classification is `unknown`.
- Fixtures establish routing and executor behavior, not model accuracy. Live accuracy evaluation remains separate.
