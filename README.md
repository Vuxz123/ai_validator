# Local Build Change Validator

POC phân tích thay đổi Unity/C# chạy song song với build local. Validator **không
chặn build**, không tự confirm và không sửa project. Workflow cố định chọn checklist
YAML, gọi agent nếu đã cấu hình, xác minh finding rồi lưu báo cáo JSON trong SQLite.

## Cài và chạy thử (Windows PowerShell)

Cần Python 3.11+ và Git trên PATH. Chạy từ thư mục repository:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe examples/demo.py
```

Demo tạo Git repo riêng dưới `.validator/demo-*`, mô phỏng confirm build đầu tiên
và giữ hai báo cáo JSON. Không chạy Unity hoặc AI; kết quả lần hai là `INCOMPLETE`
với các check nghiệp vụ `UNKNOWN`, không giả phát hiện bug từ fixture.

## Gắn vào pipeline local

```powershell
$pythonPath = '.\.venv\Scripts\python.exe'
$order = & $pythonPath -m validator order --repo D:/Games/MyGame --branch develop --profile android --target HEAD | ConvertFrom-Json
$order.build_id
$order.target_sha
# Pipeline phải build đúng $order.target_sha, không resolve HEAD lại.
# Chỉ sau khi build thành công:
& $pythonPath -m validator confirm $order.build_id
# Có thể đọc ngay; nếu chưa xong sẽ thấy QUEUED/RUNNING:
& $pythonPath -m validator report $order.build_id
```

`order` lưu job rồi khởi chạy worker nền, không chờ review. `--no-start` chỉ lưu job;
chạy `analyze <build_id>` để phân tích trực tiếp. CLI trả JSON trên stdout, lỗi trên
stderr với exit code khác 0. Tích hợp phải bắt lỗi order/confirm riêng để không làm
build thất bại. `examples/build-local.ps1` minh họa đầy đủ việc giữ exit code của build:

```powershell
./examples/build-local.ps1 -Repo D:/Games/MyGame -Branch develop -Profile android -BuildScript D:/BuildScripts/BuildGame.ps1
```

Build script nhận `-TargetSha`, chịu trách nhiệm build đúng commit đó và trả exit code.
Wrapper không tự checkout project. Nó dùng `.venv` trong repository này.

Baseline được khóa theo **đường dẫn repo chuẩn hóa + branch label + profile**. Branch
là nhãn pipeline cung cấp, không bắt buộc trùng HEAD để hỗ trợ detached checkout.
Confirm dùng SHA đã lưu, gọi lại an toàn, và build order cũ không kéo baseline lùi.
Lần đầu không có baseline trả `NO_BASELINE`. Phân tích đã order giữ nguyên baseline
dù build khác được confirm giữa chừng. Confirm chỉ là lời xác nhận build thành công
của caller; validator không kiểm tra artifact hoặc tự suy ra thành công.

## Định nghĩa checklist

Xem `workflows/rewarded_ads.yaml` và `workflows/unity_lifecycle.yaml`. Đường dẫn trong
ví dụ phải được chỉnh cho project thực tế. Điều kiện `always: true` hoặc ít nhất một
`changed_paths` khớp sẽ chọn workflow. Pattern phân biệt hoa/thường, dùng `/`; `*`
có thể khớp cả `/`, nên đây không phải đầy đủ gitignore/glob semantics.

```yaml
id: economy
version: 1
triggers:
  changed_paths: [Assets/Scripts/Economy/**]
checks:
  - id: ECONOMY_001
    description: Coin deductions must not allow a negative balance. Missing caller context means UNKNOWN.
    executor: agent
    severity: high
    context: [changed_code, diff]
    evidence_required: [Deduction location and balance guard]
```

ID workflow/check phải duy nhất. Các executor hỗ trợ: `agent`, `git_snapshot`,
`texture_pairs`, `texture_guid`, `texture_importer`.
Context provider hiện có: `changed_code`, `diff`; tên chưa cài như `reward_callers`
bị từ chối. Trường lạ, key trùng và thiếu cấu hình làm analysis `FAILED`, không bị bỏ
qua âm thầm. Loader trong `validator/workflows.py` là định nghĩa schema thực thi.
`evidence_required` hướng dẫn agent về nội dung bằng chứng; code kiểm tra vị trí và
định dạng, chưa chứng minh ngữ nghĩa. Tăng `version` khi đổi check.

## Checklist texture và .meta

`workflows/texture_metadata.yaml` chạy tự động khi ảnh hoặc `.meta` tương ứng thay
đổi trong `Assets/`, ở mọi độ sâu. Hỗ trợ PNG, JPG/JPEG, TGA, PSD, TIF/TIFF, BMP,
EXR, HDR, GIF, IFF, PICT; phần mở rộng không phân biệt hoa/thường, `.meta` dùng tên
chuẩn viết thường. Ví dụ `Assets/*.[pP][nN][gG].meta` khớp cả
`Assets/Art/UI/Icon.PNG.meta` vì matcher hiện tại cho `*` khớp `/`.

| Check | Nội dung |
| --- | --- |
| `TEXTURE_META_001` | Texture và `.meta` cùng tồn tại; bắt thiếu `.meta` hoặc `.meta` mồ côi. Xóa cả cặp là hợp lệ. |
| `TEXTURE_GUID_001` | GUID 32 ký tự hex, khác zero; cảnh báo FAIL nếu đổi GUID ở cùng đường dẫn so với baseline. |
| `TEXTURE_IMPORT_001` | Metadata YAML hợp lệ, không còn conflict marker, có mapping `TextureImporter`. |

Đây là kiểm tra bằng code, không cần backend/model. Runner đọc `.meta` từ Git ở
cả hai SHA, kể cả khi chỉ ảnh thay đổi và `.meta` không nằm trong diff. Lỗi trực tiếp
có `deterministic: true`, `verified: false` (không qua AI), vẫn được tổng hợp thành
`FINDINGS`. Xem chi tiết từng texture trong trường `details` của check.

```powershell
& $pythonPath -m validator --db .validator/project-test.db analyze $next.build_id --retry
$result = & $pythonPath -m validator --db .validator/project-test.db report $next.build_id | ConvertFrom-Json
$result.report.checks | Format-Table check_id,status,summary -Wrap
$result.report.checks | Where-Object check_id -Like 'TEXTURE_*' | ForEach-Object { $_.details } | Format-Table -Wrap
```

Chỉ kiểm tra texture bị tác động, tối đa 200 đường dẫn và 256 KiB cho mỗi `.meta`;
không đọc được/đủ dữ liệu thì UNKNOWN, không PASS. Chưa quét GUID trùng toàn repo,
reference material/prefab còn trỏ asset đã xóa, hoặc bảo toàn GUID khi rename. Không
giải mã ảnh, chạy Unity import, hay áp đặt compression/max-size/read-write; các chính
sách đó cần quy ước project riêng. Đổi GUID có chủ ý vẫn được báo để người đọc xem xét.
Các giả định về cặp asset/meta dựa trên [Unity asset metadata](https://docs.unity3d.com/Manual/AssetMetadata.html).

## Codex và OpenCode

Hai backend tích hợp sẵn dùng CLI đã cài và xác thực trên máy. Không trích/copy token
đăng nhập giữa hai công cụ. Chọn một backend cho mỗi lần phân tích:

```powershell
$pythonPath = '.\.venv\Scripts\python.exe'
& $pythonPath -m validator order --repo D:/Games/MyGame --branch develop --profile android --target HEAD --backend codex
& $pythonPath -m validator order --repo D:/Games/MyGame --branch develop --profile android --target HEAD --backend opencode
# Phân tích lại một build đã lưu, tùy chọn model:
& $pythonPath -m validator analyze BUILD_ID --retry --backend opencode --model provider/model
```

`--model` là tùy chọn: Codex dùng model mặc định của CLI (adapter bỏ user config);
OpenCode dùng lựa chọn model từ cấu hình của nó. Dùng model ID thực tế mà tài khoản
có quyền truy cập; không có tự động đổi provider hoặc model khi lỗi. `--backend`
không dùng cùng `--agent-command`. Worker nền nhận đủ backend/model; report lưu
`backend` và `requested_model` (null nghĩa là dùng mặc định, không xác nhận model thực).

Codex: `codex login`, kiểm tra bằng `codex login status`. Adapter chạy `codex exec`
với `--ignore-user-config`, `--sandbox read-only`, `--ephemeral`, JSON Schema và file
kết quả cuối. Auth vẫn do CLI quản lý; custom provider/profile trong user config không
được nạp trong backend này. Review và verify là hai session mới.

OpenCode: cấu hình bằng `opencode auth login`, xem model bằng `opencode models`.
Adapter chạy `opencode run --pure --format json --agent validator_check`, gắn request
JSON làm file đính kèm. Agent riêng có permission deny toàn bộ tool; auto-share bị
tắt. Đây là hạn chế tool ở ứng dụng, không phải sandbox hệ điều hành. Auth/provider
config của OpenCode vẫn được sử dụng; external plugins không được nạp với `--pure`.
OpenCode có thể lưu session trong dữ liệu local của chính nó.

Cả hai chạy từ thư mục tạm, chỉ nhận diff/file context đã chốt. Không gọi model đọc
working tree của game. CLI không có, auth lỗi, quota lỗi, JSON lỗi hoặc timeout đều
trở thành UNKNOWN/ERROR hoặc UNKNOWN/TIMEOUT ở check; không đổi kết quả build.
Adapter không tự retry lỗi provider. Timeout cố gắng dừng cây tiến trình của CLI.

Windows: tự nhận npm shim chuẩn của Codex/OpenCode và gọi Node/native executable
trực tiếp, không đưa prompt qua shell. Với cài đặt khác dùng
`--agent-executable C:/Tools/opencode.exe`. Hai backend yêu cầu CLI hỗ trợ các flag
trên (đã đối chiếu `--help` của CLI đang cài trên máy).

Đã thử kết nối thật trên máy này ngày 2026-09-08: cả Codex và OpenCode trả review
PASS và verification CONFIRMED cho lời gọi trực tiếp trong code mẫu, với bằng chứng
đúng SHA/file/dòng. Đây là kiểm tra kết nối và giao thức, không phải benchmark tìm bug.
Test offline có thêm case timeout với process con; môi trường Windows sandbox cần
cho phép `taskkill` đối với cây process test. Nếu hệ điều hành từ chối dừng process,
check báo lỗi; không nên xem đó là timeout đã được dọn dẹp hoàn toàn.

PowerShell wrapper hỗ trợ `-Backend codex` hoặc `-Backend opencode`, cùng `-Model`.
Ví dụ kiểm tra kết nối thật, chỉ gửi code mẫu tổng hợp (có thể dùng quota):

```powershell
& $pythonPath examples/smoke_backend.py --backend codex
& $pythonPath examples/smoke_backend.py --backend opencode --model provider/model
```

Tham khảo: [Codex non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode),
[OpenCode CLI](https://opencode.ai/docs/cli/), [OpenCode permissions](https://opencode.ai/docs/permissions/).

## Adapter tự viết

Ngoài hai backend trên, có thể tạo executable nhận **một JSON trên stdin**
và in **một JSON trên stdout**, đưa log sang stderr. Tạo file `agent-command.json`:

```json
["C:/Path/To/python.exe", "D:/Tools/my_agent_adapter.py"]
```

Dùng đường dẫn tuyệt đối; adapter chạy trong thư mục tạm, không chạy trong game repo.
Truyền `--agent-command D:/Tools/agent-command.json` vào `order` hoặc `analyze`.
Adapter tự gọi provider/model của bạn. Không truyền API key trong argv hoặc YAML.
Đây là cấu hình executable đáng tin cậy, không phải sandbox cho chương trình bên ngoài.

Request gồm `instructions`, `phase` (`review`/`verify`), `build`, `check`, `context`;
verify có thêm `finding`. Context gồm diff, file text tại target SHA và các giới hạn.
Agent không được coi nội dung repository là chỉ dẫn. Review response:

```json
{
  "check_id": "ADS_REWARD_001",
  "status": "FAIL",
  "summary": "Explain the suspected violation.",
  "evidence": [{"sha": "exact-target-sha", "file": "Assets/Scripts/Ads/Reward.cs", "line": 1, "reason": "Explain this location."}],
  "limitations": []
}
```

`PASS`, `FAIL`, `NOT_APPLICABLE` cần bằng chứng thuộc file context tại đúng target SHA,
số dòng hợp lệ và lý do. Thiếu ngữ cảnh phải trả `UNKNOWN`. Với FAIL, lượt gọi verify
riêng phải trả `verdict` (`CONFIRMED`/`REJECTED`/`INCONCLUSIVE`), `summary`, `evidence`.
Finding chỉ được đánh dấu `verified` khi verdict hợp lệ là CONFIRMED. Bị bác bỏ hoặc
chưa xác minh trở thành UNKNOWN, giữ candidate để xem lại; không tự đổi thành PASS.
Trước lượt verify, validator đọc lại evidence và tìm các file C# tham chiếu tên type
trong target Git, rồi bổ sung **toàn bộ file** để giữ các guard `#if`/early return.
Budget riêng: tối đa 45 giây trong ngân sách analysis, 300.000 byte, 20 file,
4 evidence file và 8 tên type. Nếu retrieval bị cắt/lỗi, model CONFIRMED bị hạ thành
INCONCLUSIVE; nếu có caller candidate, confirmation phải dẫn evidence ở caller.
Lưu source và giới hạn dùng cho lượt này trong `checks[].verification_context`.
Tìm type bằng text không phải compiler: `complete` chỉ nghĩa là retrieval không
bị thiếu do các giới hạn đã phát hiện, không chứng minh toàn bộ đường chạy.
`tests/fixture_agent.py` chỉ kiểm thử giao thức, tuyệt đối không phải reviewer AI.

## Trạng thái, giới hạn và phục hồi

- Analysis: `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`; tách biệt `confirmed_at`.
- Assessment: `NO_BASELINE`, `FINDINGS`, `INCOMPLETE`, `NO_FINDINGS_IN_SELECTED_CHECKS`.
  Assessment cuối chỉ nói về checklist đã chọn, không chứng nhận toàn bộ build an toàn.
- Check: `PASS`, `FAIL`, `UNKNOWN`, `NOT_APPLICABLE`; execution có `COMPLETED`,
  `SKIPPED`, `ERROR`, `TIMEOUT`. Thiếu agent không được tính PASS.
- Mặc định timeout mỗi lần gọi agent 60 giây; ngân sách thu thập context và gọi agent
  300 giây. Git có timeout tối đa 60 giây mỗi lệnh, bị giới hạn thêm bởi ngân sách
  còn lại. Chỉ gửi tối đa 30 đường dẫn đầu tiên để đọc full text, 120.000 byte ngân
  sách file và diff; phần bị bỏ được ghi rõ. Output Git khác có trần 4 MiB.
- UnityGraph MCP và tìm caller từ Git có thể bật bằng `--unity-project`; chưa có
  compiler/Unity runner hoặc theo dõi finding xuyên build. Adapter tự viết vẫn tự
  chịu trách nhiệm về process con của nó.
- Report giữ context source và định nghĩa checklist thực dùng. Bảo quản `.validator/`
  như dữ liệu mã nguồn nội bộ. YAML/adapter được đọc lúc analyze; chỉnh chúng có thể
  làm retry cho kết quả khác. Không dọn Git objects khi job cũ còn cần phân tích.
- Worker log: cạnh database, file `worker.log`. Nếu worker chết, **dừng/xác nhận process
  cũ đã dừng** rồi chạy `recover <build_id>` và `analyze <build_id> --retry`. Không tự
  phát hiện crash. Confirm lỗi có thể chạy lại thủ công.
- Dùng `--db <absolute-path>` trước tên lệnh để chia sẻ cùng database giữa các script.
  Đường dẫn mặc định `.validator/state.db` tương đối với working directory hiện tại.

## UnityGraph MCP trong analyze

Cài thêm dependency optional (UnityGraph 2.1.4 dùng MCP 1.x):

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-unitygraph.txt
$pythonPath = '.\.venv\Scripts\python.exe'
$project = 'C:/Users/DPC00176/RiderProjects/stuff-sort/StuffSort3d'
# Dựng trước cache của đúng commit; không order hoặc confirm build.
& $pythonPath -m validator index-unity --repo $project --target HEAD
$order = & $pythonPath -m validator order --repo $project --branch main --profile android --target HEAD --backend codex --unity-project $project | ConvertFrom-Json
$order.build_id
# Pipeline build đúng $order.target_sha; chỉ confirm sau khi build thành công.
& $pythonPath -m validator report $order.build_id
```

Đổi `--backend codex` thành `--backend opencode` nếu cần. `main` và `android` là nhãn
ví dụ: dùng đúng branch/profile của pipeline để lấy baseline đã confirm. Lần đầu
vẫn là `NO_BASELINE`. Với job đã order bằng `--no-start`, truyền cùng các option vào
`analyze <build_id>`; thêm `--retry` chỉ khi chạy lại job đã kết thúc.

Mặc định index **cả `Assets` và source package được commit dưới `Packages`**. Worker
export từ Git objects, parse script toàn cục, rồi parse từng prefab/scene/controller/
shadergraph và lưu quan hệ vào SQLite. Giữ bản đồ GUID toàn cục cho script, prefab
variant và shader reference; không nạp toàn bộ serialized asset vào một graph RAM.
`ProjectSettings/MonoManager.asset` bổ sung execution order. Các thư mục source có
tên `Build`, `Temp`... trong Git cũng được xét, không lọc theo tên thư mục.

Khi review, SQLite trích graph nhỏ quanh script thay đổi, rồi gọi
**MCP stdio chính thức** (`python -m unitygraph.serve`) bằng
`get_neighbors(node_id, hops=1)`. Chọn ID theo đường dẫn script để tránh chọn nhầm
seed trùng tên; cạnh graph vẫn có thể resolve sai kiểu nên luôn là hint chưa xác minh.
Hướng cạnh và vị trí nguồn lấy từ cùng index đã kiểm hash. Không mở
Unity, không dùng graph đang được Editor cập nhật, không cần `unitygraph init`.

`context.unitygraph.snapshots` giữ SHA/hash, cache hit, phạm vi, warnings, truy vấn
MCP và cạnh có hướng. `context.caller_search` tìm tên file C# trong **target Git**
để bổ sung caller qua singleton; đây là tìm text, chưa phải phân giải symbol.
File nguồn liên quan được thêm vào `context.files` để agent review/verify có thể
dẫn evidence hợp lệ. Baseline graph chỉ là ngữ cảnh lịch sử; không dùng baseline
text làm evidence cho target. Chưa tự tính semantic graph diff.

`--unity-project` cũng chuyển đường dẫn sang Unity-relative khi chọn checklist;
đường dẫn trong diff, source và evidence vẫn là Git-relative (`StuffSort3d/Assets/...`).
Checklist `CODE_IMPACT_001` áp dụng thay đổi C# dưới Assets/Packages, kể cả khi không bật
MCP. Các checklist Ads riêng vẫn cần cấu hình pattern theo project.

Index mới **không cắt ở 32 MiB/4 MiB**. Safety ceiling là 2 GiB tổng text/64 MiB mỗi
file; vượt trần thì báo lỗi và không công bố partial cache. Dùng `--graph-root` lặp
để chủ động thu hẹp nếu cần; nếu đã truyền thì nó thay các root mặc định.
Manifest ghi số file export/parse, nodes/edges, warnings và các định dạng chưa hỗ trợ.

Graph tạm cho MCP giới hạn 8 seed, 400 cạnh và khoảng 512 KB payload; metadata script
được thu gọn trước khi gửi. Mỗi snapshot trả cho agent tối đa 8 script, 50 neighbors
mỗi script, 24 KiB tổng metadata neighbor, 50 cạnh/16 KiB metadata cạnh. Tìm caller
tối đa 8 tên, 32 KiB kết quả grep, 20 file/60 KiB nguồn bổ sung. Query chỉ nhắm C#;
thay đổi thuần asset vẫn chạy các checklist đã có. Xem warnings/limitations để biết
phần bị bỏ, không suy ra an toàn từ graph rỗng.

Phạm vi file rộng không có nghĩa hiểu đầy đủ Unity: registry/Git packages chưa có
source trong commit, `Library/PackageCache`, binary assets, general `.asset`, material,
animation clip và nhiều định dạng khác chưa được parse thành quan hệ. Index chỉ giữ
cấu trúc; Inspector payload lớn được lấy từ source khi cần. Lỗi phân giải symbol và
singleton của UnityGraph vẫn cần kiểm tra bằng source. Không tải package hay chạy Unity.

Lần đầu index project lớn có thể mất vài phút. `index-unity` có timeout mặc định
1.800 giây (`--index-timeout`, tối đa 3.600), chỉ dựng cache, không sửa baseline:

```powershell
# Dùng SHA đầy đủ của target và baseline đã confirm; dựng mỗi SHA một lần.
& $pythonPath -m validator index-unity --repo $project --target $targetSha
& $pythonPath -m validator index-unity --repo $project --target $baselineSha
```

Dùng cùng `--db` và cùng graph roots khi prewarm và analyze. Cache hiện tái sử dụng
theo **đúng SHA**, chưa cập nhật incremental giữa hai SHA khác nhau. Nếu không prewarm,
analyze vẫn thử index trong budget hiện có; timeout sẽ báo thiếu context, build tiếp tục.

Nếu muốn worker tự index project lớn ngay sau order, thêm `--graph-timeout 600 --budget 1800`
vào lệnh order có `--unity-project`. Order vẫn trả ngay, pipeline không chờ index;
tăng budget chỉ cho phép worker nền chạy lâu hơn. Prewarm vẫn hữu ích nếu cả baseline
và target đều chưa có cache và tổng thời gian dựng vượt 600 giây.

`--graph-timeout` mặc định 120 giây, tối đa nửa `--budget` để dành thời gian cho agent;
bao gồm export/build/query của cả hai SHA. Process worker/server bị dừng khi hết
budget. Thiếu dependency, sai cache hoặc lỗi MCP được ghi là thiếu context; tìm
caller vẫn được thử và build tiếp tục. Assessment sẽ là `INCOMPLETE` nếu không có
finding nhưng retrieval lỗi. Report không tự confirm.
Luồng này được kiểm thử trên Windows (`taskkill /T` để dừng process tree). Chưa bảo
đảm dọn MCP server sau hard timeout trên POSIX do server dùng process group riêng.

Cache nằm trong `unitygraph-cache/` cạnh database, khóa theo repo/prefix/SHA/phạm vi/
phiên bản/schema. Mỗi cache mới chứa `index.sqlite` và `snapshot.json`; graph JSON chỉ
tồn tại tạm cho truy vấn MCP. Cache JSON cũ không được dùng thay SQLite. Chỉ cache
hoàn tất được công bố; SHA/hash sai bị từ chối. Đây là cache
local tin cậy, không phải manifest có chữ ký. Retry phải truyền lại cấu hình graph;
cấu hình này chưa được lưu làm option bất biến của order. Cache chưa tự dọn; chỉ
dọn khi không còn worker đang sử dụng. Report và cache có chứa source nội bộ.

## UnityGraph: probe độc lập

Đã có probe độc lập và hàm `validator.related_context.get_related_context()`.
Probe export text asset từ một commit vào `.validator/unitygraph-probes/`, dựng graph
local rồi lấy quan hệ trực tiếp của một script. Không chạy `unitygraph init` trong
project game, không mở Unity, không gọi model hoặc copy signing material.

```powershell
& $pythonPath -m pip install -r requirements-unitygraph.txt
& $pythonPath examples/probe_unitygraph.py --project C:/Path/UnityProject --target HEAD --script Assets/Scripts/Example.cs
```

Kết quả gồm `graph.json`, `snapshot.json`, `build-report.json`, `related-context.json`.
Manifest ghi SHA, Git-relative project prefix, UnityGraph version, hash của graph và
các file bị bỏ do budget. Hàm truy vấn từ chối SHA/hash không khớp. Đây là manifest
do probe local tin cậy tạo, không phải chữ ký xác thực graph bên ngoài.

Probe mặc định chỉ lấy `Assets/_Game`, `Assets/BravestarsSDK`, `Assets/ZeroX`; dùng
`--include-root Assets/YourFolder` (có thể lặp) để thay phạm vi. Ưu tiên script/meta,
rồi scene và prefab, giới hạn 32 MiB tổng text asset và 4 MiB mỗi file. Graph chưa đủ
project; xem `include_roots`, `omitted_by_budget` và parser warnings trước khi sử dụng.
Probe này đọc JSON trực tiếp để thử parser; đường tích hợp `analyze` ở trên dùng MCP.

## Review lại khi thiếu context

Khi agent trả `UNKNOWN` hợp lệ, runner thử mở rộng source từ đúng target SHA:
ưu tiên tên script theo thứ tự xuất hiện trong summary, rồi evidence và limitations;
nếu không có gợi ý thì dùng các C# file chưa được đọc. Chỉ chọn đường dẫn đã biết
từ changed paths/context; tối đa 4 seed, 8 tên
type, 20 file và 300 KB source trong tối đa 45 giây và budget còn lại.
Text matches là caller candidates, không phải bằng chứng call thực tế.
Mỗi seed có lượt tìm caller riêng; source caller được lấy luân phiên giữa các seed
để một type có nhiều kết quả không chiếm hết số file. Tên file được ưu tiên trước
các declaration; comment và string được bỏ khỏi bước tìm tên type. Đây là lọc
text có giới hạn, không thay thế C# compiler hay symbol resolution. Report ghi
`caller_searches` và mọi giới hạn còn lại trong retrieval.

Nếu có source mới, runner gọi review lại **đúng một lần**. Không có source mới
thì giữ `UNKNOWN`; lỗi response không kích hoạt retry. Lượt hai vẫn có thể trả
`UNKNOWN`. Nếu trả `FAIL`, finding phải qua verify cùng kiểm tra caller/guards
như trước. Mọi bước dùng chung `--budget`; mỗi model call dùng `--timeout`.
Việc này có thể thêm một model call có tính usage, không block build pipeline.

Report lưu review ban đầu, retrieval và trạng thái gọi lại trong
`checks[].review_retry`. Nếu timeout/lỗi, dữ liệu đã thu thập nằm trong
`checks[].candidate.review_retry`. Dùng `analyze BUILD_ID --retry` cùng backend,
Unity project và budget như lần trước để phân tích lại report cũ.

## Dùng chung cho nhiều project

Engine không cần biết tên game. Rule pack hiện là một workflow YAML có `id` và
`version`; cấu hình project ánh xạ source groups vào đường dẫn riêng. Ví dụ ở
`examples/project.generic.yaml`. Sao chép file này, sửa mapping và dùng
`--project-config PATH` với `order`, `analyze` hoặc `preview`.

- `unity_root`: thư mục Unity tương đối với Git root, `.` nếu trùng root.
- `source_groups`: glob tương đối với Unity root; Ads dùng nhóm `ads`, lifecycle
  dùng `ui`. `first_party` và `third_party` chỉ phân loại evidence, không bỏ finding.
- `rule_packs`: danh sách workflow ID bật; bỏ trường này để bật tất cả workflow
  trong `--workflows`. `common` luôn được bật nếu có trong thư mục workflow.
- Patterns dùng Python `fnmatchcase`, phân biệt hoa/thường; `*` có thể khớp `/`.
  Đây không phải gitignore glob. Không dùng đường dẫn tuyệt đối hoặc `..`.

Xem trước routing, không tạo build/database, không index graph và không gọi model:

```powershell
$preview = & $py -m validator preview --repo $project --baseline $baselineSha --target $targetSha --project-config .\project.yaml | ConvertFrom-Json -ErrorAction Stop
$preview.routing | Format-Table workflow_id,version,status,missing_groups,matched_paths -Wrap
```

`SELECTED`: sẽ chạy; `NO_MATCH`: không có changed path khớp;
`DISABLED`: không bật pack; `MISSING_MAPPING`: thiếu source group của pack đã bật.
Thiếu mapping làm report `INCOMPLETE` khi không có finding được xác nhận, không
được hiểu là PASS. Chỉ pattern khớp path không chứng minh module được kiểm tra đủ.

Chạy trên build đã order (thêm `--retry` nếu build đã analyze):

```powershell
$result = & $py -m validator --db $db analyze $buildId --retry --project-config .\project.yaml --backend codex --timeout 120 --budget 900 | ConvertFrom-Json -ErrorAction Stop
$result.report.routing | Format-Table workflow_id,status,missing_groups -Wrap
$result.report.checks | Format-Table check_id,status,verified,summary -Wrap
```

Không cần UnityGraph để chuẩn hóa Unity root hoặc chạy texture checks. Nếu bật
retrieval bằng `--unity-project`, đường dẫn phải khớp `unity_root` trong config.
Order tự khởi động worker có chuyển tiếp `--project-config` bằng đường dẫn tuyệt đối.
Report lưu config hiệu lực, hash, định nghĩa/version workflow, routing và
`checks[].source_ownership` (`first_party`, `third_party`, `mixed`, `unknown`).

**Giới hạn hiện tại:** config được đọc khi analyze, chưa đóng băng tại order.
Giữ config không đổi trong lúc worker chạy và truyền lại cùng config khi retry;
report lưu bản đã dùng để đối chiếu. Không có config thì giữ routing Ads/UI cũ
và ghi `routing_mode: legacy`. Không có registry/download pack hoặc tự suy ra mapping.
Các fixture đa layout trong `tests/test_project_config.py` kiểm tra engine/routing;
đánh giá độ chính xác của agent vẫn cần bộ case và live evaluation riêng.

## Đánh giá checklist Ads/UI bằng backend thật

Workflow AI hỗ trợ `objective`, `instructions`, `context_requests`, `verdicts`.
Hướng dẫn viết rule/case mới: [Authoring AI Workflows](docs/authoring-ai-workflows.md).
Các fixture hiện nằm trong `examples/checklist_cases/*.yaml`; dùng `--cases-dir`
và `--workflows` để chạy bộ tự viết, không cần chỉnh Python.

`examples/evaluate_checklists.py` tạo 6 Git fixture riêng: `ads_good`, `ads_bad`,
`ads_unknown`, `ui_good`, `ui_bad`, `ui_unknown`. Tổng cộng 9 check được chấm.
Chỉ bật pack Ads hoặc UI tương ứng và common; không bật code impact hoặc UnityGraph.
Good kỳ vọng PASS, bad kỳ vọng FAIL đã verify, unknown kỳ vọng UNKNOWN do thiếu source.
Đây là kỳ vọng đánh giá, không ép kết quả agent.

Chuẩn bị fixture không tốn usage:

```powershell
$eval = & $py examples/evaluate_checklists.py --prepare-only | ConvertFrom-Json -ErrorAction Stop
$eval.directory
```

Chạy một case trước, sau đó toàn bộ (gọi model, tính usage):

```powershell
$eval = & $py examples/evaluate_checklists.py --backend codex --case ads_bad | ConvertFrom-Json -ErrorAction Stop
$eval.cases.checks | Format-Table check_id,expected,actual,verified,matched -Wrap

$eval = & $py examples/evaluate_checklists.py --backend codex --timeout 120 --budget 600 | ConvertFrom-Json -ErrorAction Stop
$eval | Select-Object evaluated_checks,matched_checks,directory
$eval.cases | ForEach-Object { $caseName = $_.case; $_.checks | Select-Object @{Name='case';Expression={$caseName}},check_id,expected,actual,verified,matched,execution_status }
```

Đổi `--backend opencode`, thêm `--model provider/model` khi cần. `--case` có thể lặp.
Budget là **mỗi case**; mỗi check có thể thêm lượt review/verify. Không chạy model
song song. Mỗi lần gọi script tạo run mới; prepare-only không được tái sử dụng tự động.
Report/SQLite/config/source và `summary.json` được giữ trong `.validator/checklist-evals/`.
Labels nằm ngoài Git/context agent. Target không được confirm.

Exit code 1 nghĩa là có mismatch/lỗi; vẫn đọc JSON để xem kết quả. UNKNOWN do timeout,
lỗi backend hoặc không có check không được tính là đạt case thiếu context. Đừng đổi
nhãn để làm điểm đẹp: xem source, evidence và verification của report trước.

Fixture dùng source C# mô phỏng luồng gọi, không chạy Unity. Case unknown cố ý thiếu
implementation dependency và không phải project có thể compile. Bộ test này đo một
số hành vi hẹp, chưa chứng minh độ chính xác trên game thật.

## Review mở nhiều lượt

### Evaluation cho hướng tự điều tra

`examples/evaluate_investigation.py` chạy workflow `code_impact` trên 8 Git fixture:
`project_null` (FAIL first_party), `sdk_callback` (FAIL third_party), `project_clean`
(PASS), `external_unknown` (UNKNOWN do thiếu implementation/contract bên ngoài).
Đây là source tổng hợp, không build Unity và không sửa game thật.

Bốn case chống báo sai đều kỳ vọng PASS cho delta trong phạm vi fixture:

- `caller_guard`: bỏ null guard ở callee, nhưng caller kiểm tra null trước mọi lần gọi.
- `unreachable_method`: method private có lỗi mới nhưng không thể được entrypoint gọi tới.
- `preexisting_defect`: lỗi null đã có và được gọi từ baseline; target chỉ thêm hằng số
  không liên quan. PASS ở đây nghĩa là không có lỗi mới do delta, không phải chương trình sạch lỗi.
- `namespace_collision`: caller dùng alias tới `Feature.Formatter`; code lỗi mới nằm
  trong `Vendor.Formatter`. Hai type trùng tên ngắn không tạo thành cùng call path.

Tiền đề chạy của bốn case này xác định một chương trình đóng với một entrypoint,
không reflection/dynamic dispatch. Đây là giới hạn fixture, không được suy ra cho game thật.
Caller không đổi được giữ ở baseline, để agent có thể phải chủ động đọc thêm source.

```powershell
& $py examples/evaluate_investigation.py --prepare-only
$eval = & $py examples/evaluate_investigation.py --backend codex | ConvertFrom-Json -ErrorAction Stop
$eval | Select-Object evaluated_cases,matched_cases,expected_findings,matched_findings,unexpected_confirmed_findings,directory
$eval.cases | Format-Table case,expected,actual,matched,matched_findings,unexpected_confirmed_findings,stop_reason -Wrap
```

Đổi backend thành `opencode`, thêm `--model`, hoặc chọn `--case sdk_callback` (lặp
`--case` để chọn nhiều case). Timeout mặc định 120 giây/model call, budget 600 giây/case.
Live run tiêu thụ usage. Exit 1 khi có case không khớp; JSON vẫn được xuất để xem lỗi.
Report và bản YAML thực dùng được giữ trong `.validator/investigation-evals/run-*/`.

Custom bằng YAML trong `examples/investigation_cases`, hoặc `--cases-dir <folder>`.
`baseline_files` là snapshot ban đầu; `files` ghi đè/thêm file ở target, giữ các file
baseline khác. `execution` chỉ nêu entrypoint và tiền đề chạy, không tiết lộ lỗi.
`expected` chứa status và danh sách finding có `file`, `start_line`, `end_line`,
`ownership`, `summary_any` (ít nhất một cụm từ cơ chế lỗi phải xuất hiện trong summary).
Nhãn và tên case không gửi model. Chỉ bật pack `code_impact`, không thêm checklist case.

Chấm finding theo evidence, ownership, verify và cụm từ; finding thừa làm case không
khớp. UNKNOWN do timeout/lỗi tool/hết vòng không được chấm đúng. Đây là rubric từ khóa,
không phải kiểm chứng ngữ nghĩa hoàn chỉnh: cần đọc report khi đánh giá chất lượng.
Test offline chỉ xác nhận harness; kết quả tám fixture không đại diện độ chính xác
trên toàn bộ project.

`code_impact` version 5 dùng `executor: investigation`. Không cần case hoặc kỳ vọng
nghiệp vụ. Agent đọc diff, đặt giả thuyết, yêu cầu engine đọc file/tìm symbol/query
UnityGraph rồi nộp findings. Chỉ engine gọi công cụ; backend không được thực thi
command tùy ý. Checklist `executor: agent` vẫn giữ flow review/retry/verify.

Giới hạn mặc định: 6 vòng agent (tối đa 5 vòng truy xuất), 3 request/vòng, 5 findings,
75 KB mỗi source read, 300 KB source bổ sung. Search chỉ C#, tối đa 40 path/request;
graph chỉ script C#, tối đa 20 giây/request và cần `--unity-project`. Mọi thao tác
dùng chung `--budget`; `--timeout` giới hạn mỗi model call. Yêu cầu lặp bị từ chối.
Source baseline giữ riêng, không dùng làm evidence target. Không có code execution,
Unity runtime validation hoặc sửa game trong flow này.

Tùy chỉnh trong `project.yaml` (bỏ qua sẽ dùng các giá trị mặc định):

```yaml
investigation:
  max_rounds: 6
  verify_reserve_seconds: 120
```

`max_rounds` nhận 2–12; reserve nhận 0–600 giây. Phần dành cho verify nằm trong
`--budget`, giới hạn thêm ở một phần ba thời gian còn lại khi bắt đầu investigation.
Search nhận chuỗi literal một dòng tối đa 160 ký tự, ví dụ `class Singleton`.
Agent được hướng dẫn ưu tiên `find` theo field/GUID rồi `read_lines` cho prefab/scene.

Chỉ bật `code_impact` trong `rule_packs` nếu muốn chạy riêng hướng 2 (`common` vẫn
được chọn). Chạy lại build đã có:

```powershell
$result = & $py -m validator --db $db analyze $buildId --retry --project-config .\project.yaml --unity-project $project --backend codex --timeout 120 --budget 900 | ConvertFrom-Json -ErrorAction Stop
$impact = $result.report.checks | Where-Object check_id -eq CODE_IMPACT_001
$impact | Format-List status,verified,summary,limitations
$impact.investigation.findings | Format-Table status,verified,summary -Wrap
```

Mỗi finding qua verify riêng; xem `investigation.findings` để phân biệt confirmed và
candidate chưa xác nhận. `investigation.rounds` lưu quyết định agent;
`investigation_context` lưu source bổ sung và tool results. Ownership nằm trên từng
finding. PASS chỉ là kết luận trong phạm vi đã đọc, không chứng minh toàn project an
toàn. Hết vòng, lỗi protocol hoặc retrieval không đầy đủ được ghi rõ; model trả PASS
sau tool failure sẽ bị hạ thành UNKNOWN. Các report cũ không tự thay đổi.

`investigation.stop_reason` phân biệt `agent_finished`, `final_round_finished`,
`round_limit`, `investigation_budget`, `agent_timeout` và `error`.
`review_outcome` tách kết luận findings khỏi `coverage`: danh sách source đã cung cấp,
file chỉ có đoạn trích, changed paths chưa có source và các giới hạn. Source đã cung
cấp không chứng minh agent đã đọc hết. Thiếu test thiết bị được ghi vào coverage;
chỉ giữ UNKNOWN khi thiếu bằng chứng để giải quyết một nghi vấn cụ thể, hoặc engine
gặp lỗi/giới hạn chưa giải quyết. PASS vẫn chỉ áp dụng trong phạm vi review.

## Thành phần source

### Đọc một phần prefab/scene lớn

Investigation hỗ trợ `find` (tìm chuỗi literal trong một file) và `read_lines`
(khoảng dòng gốc, 1-based inclusive, tối đa 400 dòng). `find` trả tối đa 10 vị trí
kèm 12 dòng hai phía, ghép vùng trùng nhau. Mỗi request trả tối đa 24 KB source;
engine chỉ đọc blob Git tối đa 16 MiB và vẫn dùng deadline/budget chung.

```json
{"kind":"find","path":"Game/Assets/Manager.prefab","query":"autoAuthenticate","snapshot":"target","start_line":0,"end_line":0}
```

Agent có thể dùng số dòng trả về để yêu cầu `read_lines` quanh component cần kiểm tra.
Đây là cửa sổ text, chưa phải parser xác định toàn bộ block Unity YAML. Agent cần đọc
đủ m_Script/reference và giới hạn component trước khi kết luận field thuộc object nào.
`source_excerpts` lưu đoạn target với số dòng gốc; `baseline_excerpts` chỉ là lịch sử.
Evidence ở dòng chưa được cung cấp bị từ chối. Đoạn trích luôn có `partial: true`;
không suy ra một guard/reference không tồn tại chỉ vì không thấy nó trong đoạn trích.
Full-file verification vẫn có thể báo thiếu context nếu vượt budget riêng của nó.

`read`, `find`, `read_lines` đọc thêm `.xml` trong `Assets/Packages` và các file
`.asset`, `.txt`, `.xml` trong `ProjectSettings` của đúng Unity project. Ví dụ:
`find` với `query: applicationIdentifier` tại `StuffSort3d/ProjectSettings/ProjectSettings.asset`.
Giới hạn byte/dòng/thời gian giữ nguyên; UnityGraph và search vẫn chỉ dành cho C#.
File không có trong Git snapshot được báo rõ, không đọc thay bằng working tree.
Không có trong Git chưa chứng minh file được sinh lúc build: agent phải đọc generator
để xác định điều đó và ghi giới hạn nếu chưa có output cần đối chiếu. Lỗi đọc vẫn
được giữ trong report; thiếu bằng chứng cho nghi vấn cụ thể vẫn có thể trả UNKNOWN.

`validator/store.py`: lifecycle SQLite; `git.py`: snapshot/diff; `workflows.py`:
schema và routing; `agent.py`: giao thức; `runner.py`: pipeline; `__main__.py`: CLI.
`tests/` dùng unittest, Git repo tạm và adapter giả để kiểm tra hành vi thực tế.
