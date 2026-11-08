# find_items：真实 ItemContainer 验证记录

改名说明（2026-11-08）：项目现名为DeskWeft（Python包/CLI：`deskweft`）。本报告原有的`winmcp`命令、路径、模块、desktop名称及源码哈希保留为改名前原始证据，不倒填为新名称；纯命名修改须另经新离线与部署验收，也不表示本报告GUI任务已重跑。当前入口和兼容存储规则见[实施交接](../specs/2026-11-08-implementation-handoff.md)。

日期：2026-11-08。结论只适用于下述合成数据和本机 provider。WPF 的 300 项合成名单与独立夹具清单相符，保留了 12 个同名项目；部分虚拟项的 IsOffscreen 读取失败，因此不声称元数据完整。Explorer 的 150 个项目名与实际目录文件集相符，元数据均读到。两组重叠页均一致，均未把末页 reached_end 当成单次 complete 或业务全量证明。

本报告与 README、设计稿中的历史 T1–T9 和 QQ/Electron 测量分开保存；不补造旧环境，也不把这两组结果推广为所有 ItemContainer provider 的保证。

## 执行边界与环境

两份 live 脚本使用 `fastmcp.Client(server.mcp)` 作为进程内 MCP 客户端，经真实生成的 UIA worker 进入 Windows COM/provider。它们覆盖 MCP 参数包装、worker 协议、定位及真实 FindItemByProperty；**本次传输不是 HTTP，也未重启或验证当前已安装服务**。数据均为测试专用的合成对象/空文件，不读取用户业务数据。

| 项目 | 本轮环境 |
|---|---|
| Windows | Windows-11-10.0.26300-SP0 |
| Python | 3.14.7，MSC v.1944 64 bit (AMD64)；构建标签 `tags/v3.14.7:823f032, Aug 5 2026, 10:51:32` |
| 解释器 | `C:\Users\32677\AppData\Local\winmcp\.venv\Scripts\python.exe` |
| windows-mcp | 0.8.8 |
| FastMCP | 4.1.6 |
| 工具 | 本工作仓库的 `find_items`，固定分派到 `winmcp.items.find_items` |

`wall_ms` 是 live 客户端包住 MCP 调用的耗时，`took_ms` 是工具结果中的操作耗时；差额可能包含 worker 启动等工作。`provider_calls` 只计 FindItemByProperty，不计全部 COM 元数据查询。以下均为单次运行观测，不是性能基准、延迟保证或不同路线的同范围比较。

## WPF：虚拟化、重名、远端过滤和超时恢复

夹具由 [itemcontainer.ps1](../../tests/fixtures/itemcontainer.ps1) 创建，验证入口为 [live_itemcontainer.py](../../tests/live_itemcontainer.py)。原运行目录为 `.superpowers/sdd/2026-11-08-itemcontainer-live/runs/fixture-20261108-01/`。

夹具在 `2026-11-08T06:27:38.8803062Z` 启动，manifest 记录 300 个对象，初始仅实现 13 个可视项目；ItemContainer peer 可用。每项独立赋予 Key，AutomationId 为 `fixture-0000` 至 `fixture-0299`，因其由夹具生成且在本次范围唯一，才用作跨页业务身份。每 25 项一次的 `Fixture duplicate` 共 12 个；末项为 `Fixture item 0299`、Key `fixture-0299`。本轮 PID 31836、HWND 2492382 和 selector `{"automation_id":"ItemContainerFixtureList"}` 仅为记录，不可作为下轮常量。

最终复跑命令（仓库根目录）：

```powershell
& "$env:LOCALAPPDATA/winmcp/.venv/Scripts/python.exe" -B tests/live_itemcontainer.py --ready .superpowers/sdd/2026-11-08-itemcontainer-live/runs/fixture-20261108-01/ready.json --out .superpowers/sdd/2026-11-08-itemcontainer-live/runs/fixture-20261108-01/mcp_result_final.json
```

| 调用 | 返回项 | provider_calls | wall_ms | took_ms | metadata_complete | complete | IsOffscreen 错误项 |
|---|---:|---:|---:|---:|---|---|---:|
| page_0 | 100 | 101 | 1965.1 | 261.2 | false | false | 86 |
| page_99 | 100 | 200 | 295.3 | 289.1 | false | false | 100 |
| page_198 | 100 | 299 | 339.2 | 333.9 | false | false | 100 |
| page_297 | 3 | 301 | 234.6 | 230.8 | false | false | 3 |
| far_name | 1 | 2 | 109.5 | 107.3 | false | false | 1 |
| duplicates | 12 | 13 | 140.2 | 137.8 | false | false | 11 |
| missing | 0 | 1 | 116.8 | 114.2 | true | true | 0 |
| unselected_bool | 2 | 3 | 115.2 | 112.8 | true | false | 0 |
| far_automation_id | 1 | 2 | 120.3 | 118.0 | false | false | 1 |
| recovery | 1 | 2 | 1679.0 | 126.0 | false | false | 1 |

四个未过滤页的 start_index 为 0、99、198、297，max_items 均为 100，timeout_ms 为 15000。前三页 has_more=true，next_start_index 分别为 100、199、298；末页 reached_end=true、has_more=false。交付的实际 index 区间为 0–99、99–198、198–297、297–299，重叠后恰好覆盖 300 项。后页重扫的前缀未返回元数据；不能仅查首 100 项和末 3 项就声称交付了 300 项。

`far_name`、`duplicates`、`missing` 使用 Name 属性 30005；末项 ID 查询使用 AutomationId 30011；`unselected_bool` 使用 IsSelected 30079、JSON false、max_items=2，has_more=true、next_start_index=2。这些是该 provider 的支持性证据。不存在名称的查询返回空且 complete=true，只表示这个过滤查询完整结束。

例如 index 14、ID `fixture-0014` 的 IsOffscreen 报 `COMError`，HRESULT 为 -2147220991；name、automation_id、control_type 仍保留。错误消息本身不作为业务文本。四页的任务必需名单字段可核对，但 metadata_complete 和 complete 必须保持 false；未通过自动 Realize、滚动、选择或焦点操作去补齐附加字段。所有成功查询的 snapshot=false、result_truncated=false。

超时探测单独设 timeout_ms=1，返回 `desktop call timed out`、execution_state=unknown；本次 wall_ms=21.2、worker 清理耗时 14.3ms。随后独立只读 recovery 查询经重建 worker 成功。未知执行状态没有被改写成“未执行”，也不支持自动重放先前副作用。

最终验证记录为 known_item_count=300、unique_fixture_ids=300、duplicate_names_preserved=12、overlapping_pages_agreed=true、passed=true。初版测试曾假设 RuntimeId 跨调用稳定，现场否定了该假设；最终重叠页记录 **cross_call_runtime_id_changes=2**。测试改为核对独立 fixture ID、实际交付索引和重叠，不删除变化观测。RuntimeId 仍只作为本次枚举身份/循环证据，不是跨页主键或持久句柄。

另一个修复由单元回归暴露：RuntimeId 缺失后又恢复的混合路径仍需检测重复元素；红转绿后重新执行了上表 WPF 测试。此项由假 provider 测试证明边界，不能假称现场 provider 曾实际发生该循环。

WPF 窗口设置 ShowActivated=false。夹具和成功工具调用的前台前后样本均为 6359280；未采样光标，两点前台样本不能证明调用中间从未短暂夺焦。

## Explorer：实际目录清单与准确内容容器

夹具入口为 [explorer_items.ps1](../../tests/fixtures/explorer_items.ps1)，支持 Open、Reveal、Close；验证入口为 [live_explorer_items.py](../../tests/live_explorer_items.py)。原运行目录为 `.superpowers/sdd/2026-11-08-itemcontainer-live/runs/explorer-20261108-01/`，其中 `item-files` 含 150 个已知空文件 `fixture-0000.txt` 至 `fixture-0149.txt`。

归属证据是新 HWND 不在启动前 baseline 中，并且 Shell 的精确 folder URL 对应该合成目录；launcher_pid=3040 单独不能证明 Explorer 窗口归属。helper 后续按精确 HWND/folder 对再次核验。本轮顶层 HWND 2165380，内容 child HWND 1182728 经 IsChild 确认属于它。实际内容的 class 为 UIItemsView、control_type 为 ListControl、Name 为“项目视图”、AutomationId 为空。另有 TabListView/ListView 的 ItemContainer，native HWND 为 0；不能按第一个容器或仅控件类型选择。诊断遍历路径也不是公开 nth selector。

初始隐藏窗口扫描只访问 7 个节点、未找到容器，partial=false、27.9ms。将自己窗口显示但不激活后扫描访问 348 个节点，找到 2 个容器，partial=true 且 depth_limit_reached=true、353.0ms。因此隐藏时空结果不能证明 Explorer 没有 ItemContainer，后一次扫描也不能被写成完整树唯一性证明；之后重新核验归属/元数据，并通过普通 MCP 的精确 selector 定位。

实际 MCP target 为 `{"native_hwnd":1182728,"control_type":"ListControl"}`，顶层 hwnd 为 2165380。执行命令：

```powershell
& "$env:LOCALAPPDATA/winmcp/.venv/Scripts/python.exe" -B tests/live_explorer_items.py --ready .superpowers/sdd/2026-11-08-itemcontainer-live/runs/explorer-20261108-01/explorer-ready.json --content-hwnd 1182728 --out .superpowers/sdd/2026-11-08-itemcontainer-live/runs/explorer-20261108-01/mcp_result.json
```

| 调用 | 返回项 | provider_calls | wall_ms | took_ms | metadata_complete | complete |
|---|---:|---:|---:|---:|---|---|
| page_0 | 100 | 101 | 2859.8 | 1198.6 | true | false |
| page_99 | 51 | 151 | 1859.3 | 1855.6 | true | false |
| far_name | 1 | 2 | 730.8 | 728.5 | true | true |
| missing | 0 | 1 | 730.7 | 728.5 | true | true |
| verified_child_root | 2 | 3 | 未单独采样 | 2.1 | true | false |

前两页 timeout_ms=15000，交付 index 0–99 与 99–149；末页 reached_end=true、has_more=false，因偏移99而 complete=false。实际返回名包含 `.txt`；重叠名称一致，去重后的 150 名与独立读取的文件名集合精确相等。不能用本 provider 的位置式 AutomationId（例如 `"0"`）代替已验证业务身份。

`verified_child_root` 另以已经验证归属的内容 HWND 和显式 target=""、max_items=2 读取根。该样本与顶层定位的 100 项调用范围不同，不能据 2.1ms 断言根直读的整体效率更高。所有五个结果无字段错误、result_truncated=false、snapshot=false；工具前台前后样本均为 6359280、foreground_changed=false，发现阶段同样如此。

最终验证记录为 known_empty_files=150、distinct_names=150、overlap_agreed=true、far_name_filter=true、owned_child_root=true、passed=true。它证明静止合成目录的本次覆盖，不证明动态目录仍可跨页拼接成快照。

## 原始证据与清理

原始 JSON/日志保存在本机 `.superpowers/sdd/2026-11-08-itemcontainer-live/` 下的运行目录，不把临时数据混入历史测量表。可复跑入口保存在 tests 中；完整原始数据随本机运行记录保存，未承诺每个 checkout 都携带这些临时文件。

| 目录或文件 | 内容 |
|---|---|
| `runs/fixture-20261108-01/ready.json` | 独立 WPF 总量、身份及初始实现数 |
| `runs/fixture-20261108-01/mcp_result.json` | 早一次成功运行，保留不覆盖 |
| `runs/fixture-20261108-01/mcp_result_final.json` | 循环修复后的最终 WPF 结果 |
| `runs/fixture-20261108-01/stdout.log`、`stderr.log` | 本轮均为空 |
| `runs/fixture-20261108-01/closed.json` | 夹具正常关闭记录 |
| `runs/explorer-20261108-01/explorer-ready.json` | 独立文件集与归属记录 |
| `provider-scan.json`、`provider-scan-shown.json`、`container-identities.json`（Explorer 目录） | 隐藏/显示差异与内容容器身份 |
| `runs/explorer-20261108-01/mcp_result.json` | 最终 Explorer MCP 结果 |
| `runs/explorer-20261108-01/cleanup-verification.json` | 精确窗口关闭后的核验 |

SHA256：

```text
WPF mcp_result_final.json
83cd77ba23c8fb53fe7d44c5855846712ccb87147b1500d98b9100bc325c16c2
Explorer mcp_result.json
3dfbb15e254fb173f9a2a26b24a4ce6c70e3a8ea0f04f36c52761b6257e34fd3
tests/fixtures/explorer_items.ps1（与本轮实际 launcher 一致）
b6747bb2d818b25ca7eaeb9d193c39b7b22be22fbdba98a815a4d56fe2bc00f3
```

WPF 在 `2026-11-08T06:40:37.7554484Z` 正常关闭，closed.json 的 PID 与夹具相同。`2026-11-08T06:41:22.1454960Z` 核验两组自己的窗口均不存在，Explorer HWND 也不再注册于 Shell。Explorer 关闭先核对精确 HWND/folder，再调用该 Shell 窗口的 Quit；未按启动器 PID 清理所有 Explorer。150 个空文件保留，原数据未删除。live 脚本结束时也关闭自己的 worker。

本轮最终独立单元测试输出为 **313 tests，13.602s，OK**，其中 items 的 17 项覆盖真实 VARIANT 构造配假 COM 等分支；它与上述真实 provider 测试分别计证。既有 fake socket ResourceWarning 和 FastMCP inputSchema 弃用警告仍存在，不被本报告解释为新增生产故障。skill quick_validate 与 git diff --check 亦通过。

## 复跑入口

使用新的运行目录，重新确认前台授权、manifest 和归属；不可复用本报告的旧 HWND。以下 WPF 步骤必须使用两个终端。终端 A 启动 STA 夹具后会持续运行，保留该终端：

```powershell
powershell.exe -NoProfile -Sta -ExecutionPolicy Bypass -File tests/fixtures/itemcontainer.ps1 -RunDirectory .superpowers/sdd/2026-11-08-itemcontainer-live/runs/fixture-new
```

终端 B 在仓库根目录等待新 ready.json（最多15秒），再运行 live 入口；finally 只写这个夹具的关闭请求，夹具读取后正常退出，终端 A 返回：

```powershell
$taskRun = '.superpowers/sdd/2026-11-08-itemcontainer-live/runs/fixture-new'
$taskReady = Join-Path $taskRun 'ready.json'
$taskDeadline = [DateTime]::UtcNow.AddSeconds(15)
while (-not (Test-Path -LiteralPath $taskReady)) {
    if ([DateTime]::UtcNow -ge $taskDeadline) { throw 'Fixture did not become ready within 15 seconds; inspect terminal A' }
    Start-Sleep -Milliseconds 250
}
try {
& "$env:LOCALAPPDATA/winmcp/.venv/Scripts/python.exe" -B tests/live_itemcontainer.py --ready .superpowers/sdd/2026-11-08-itemcontainer-live/runs/fixture-new/ready.json --out .superpowers/sdd/2026-11-08-itemcontainer-live/runs/fixture-new/result.json
} finally {
    New-Item -ItemType File -Path (Join-Path $taskRun 'close.request') -Force | Out-Null
}
```

Explorer 用 explorer_items.ps1 的 Open 建立新合成目录/窗口，Reveal 显示已核验归属的该窗口而不激活，再定位并重新验证真实内容 HWND。把新 manifest 路径和 child HWND 传给 live_explorer_items.py；它会检查文件集和 IsChild。结束时用同一运行目录执行 Close，helper 将重新核对精确 HWND/folder。不要用旧内容 HWND 或 TabListView 顶替目标。

通用 invoke_pattern 的 args 仍不接受列表内 null 或任意 Control 输入；本次专用适配只托管 FindItemByProperty 的 NULL 起点与同调用续项。动态顺序、相等业务项被 provider 跳过、字段读取错误、预算截断和缺乏独立总量的场景仍需分别报告，不用单个 complete=true 消除这些限制。
