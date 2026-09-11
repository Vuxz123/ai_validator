# Bounded Open Investigation

Code impact uses an investigation executor; checklist agents keep review/retry/verify.
The agent chooses read, symbol search or UnityGraph requests, then submits zero to five
findings. Engine executes requests from frozen baseline/target only. No project code
execution, writes, arbitrary shell or arbitrary network requests are exposed.

Protocol: investigate responses contain action, requests, findings, status, summary,
evidence, limitations. Six agent rounds by default, three requests per round, five findings,
75 KB per source read and 300 KB added source total. All calls share analysis deadline;
graph queries have an additional 20-second cap. Baseline source is historical and
cannot support target evidence. Repeated requests are not executed again.

Each finding is separately validated and passed through existing independent verify.
Report retains tool audit, added source, individual verdicts and unresolved coverage.
No findings does not imply complete coverage; PASS means only no findings in reviewed
scope with source evidence. Invalid protocol/tool failures/caps stay visible, never
silently create PASS. No model accuracy claim without a live evaluation.

Source-window extension: find literal strings inside one committed file and return
bounded context windows; read_lines fetches up to 400 original lines. Source excerpts
are stored separately from full files and baseline excerpts. Evidence validator only
accepts supplied target lines. Read cap 16 MiB per Git blob, output cap 24 KB/request,
shared 300 KB additional source allowance. This is text slicing, not Unity YAML block
parsing. Verified on the real frozen PlayGameManager prefab: 7,587 lines, matching
autoAuthenticate at original line 245 without passing the full prefab to the agent.

2026-09-11: Project configuration accepts investigation.max_rounds (2–12, default 6)
and verify_reserve_seconds (0–600, default 120). Reserve is capped at one third of
remaining analysis time and retained within the original deadline for verification.
C# search accepts single-line literal text, including declaration fragments.
Reports separate review_outcome from supplied-source coverage and record stop_reason.
Runtime tests outside the static review scope remain limitations; missing evidence
for a specific unresolved hypothesis still requires UNKNOWN. Tool errors remain visible.
