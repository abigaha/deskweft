---
name: windows-app-automation
description: Use when automating or probing Windows applications, including native controls, UIA/Legacy, Electron, UWP/WinUI, self-drawn interfaces and virtualized lists; when reads/actions fail; or when choosing an official API, CLI or export instead. 控制陌生软件、读不到界面、点击不生效、完整列表采集、自动化路线选择。
---

# Windows 应用自动化

## 开始前：确认目标和实际可用工具

1. 看客户端实际工具清单；本文中的新增工具未注册时记作“工具尚未实现”，
   不编造调用。用 windows() 确认 hwnd、pid、标题与类，app_info 确认 exe/版本来源。
2. 已知版本时 recall("name@version")；未知时 recall(name) 看候选。
   先排除不适用的版本/环境和当前不允许的副作用，再按 rank 看。
   用户正在操作时排除 uses_foreground=true；用户离开也不自动构成授权。
3. 精确、本版本、非继承的 rank>=2 可复用路线，但仍验证每次目标效果；
   rank=1 逐步验证；rank=0、家族/继承候选或未命中先探测。
   正文截断时用 plan_id/body_offset 续读，核对每片 revision 一致，再拼完整步骤。
   reviewed/proven 不是本次业务操作授权，不能据此关闭、提交或重启应用。

## 基础探测：把不同原因分开

1. see(hwnd, with_tree=true) 同时看截图、elements、native_children、timed_out。
   先核对窗口身份是否变化、是否隐藏/最小化、是否触及元素上限。
2. 空树可能来自过滤、超时、provider 错误或启动条件；不能仅凭空结果判框架。
   截图空白与树不可读是两个问题，分别试验并分别记录。
3. 读取先用明确只读接口；写操作先用 click/type_text 等现有专用工具。
   需要通用模式/原生消息时按各自权限和数据契约执行。目标未知、重名或树不完整时
   不调用 click 去碰运气；改用唯一目标、明确 child HWND 或记录定位缺口。
4. 每次失败写清“未试、权限未满足、工具缺能力、provider报错、调用完成但效果未达成”
   中的哪一种；某一条路线失败后按下表换方向，不能推成整个应用无法自动化。

## 按界面与任务选择路线

| 观测或任务 | 下一步思路 | 如何验证、何时换路线 |
|---|---|---|
| 原生 Win32/WinForms 子控件 | 从 native_children 取 child HWND/class，按钮和文本先用专用工具；必要时用托管 WM_GETTEXT/SETTEXT、BM_GETCHECK、CB/LB_GETCURSEL | 文本读回相等，按钮检查目标状态/计数，选择检查索引；入队不等于生效。没有匹配控件类时转 UIA，不推断整个程序不支持。 |
| 有语义 UIA 的 WPF/WinUI/其他应用 | 精确名称或 AutomationId 定位，按 provider 暴露的 Value/Text/Selection/ExpandCollapse/Scroll 等接口读取或操作 | patterns 的七项摘要不是全集；按需尝试其他已封装 pattern。明确区分目标歧义、未封装、未暴露和方法异常。 |
| Chromium/Electron/浏览器树空或失焦后消失 | 核对进程、已有 flags、前后台对照，再检查下面的无障碍与防降级条件；已有合法浏览器语义接口也可作为替代 | 重复读取同一窗口比较命名元素与稳定性，不把单次非空当长期有效；单实例不采纳 flags 时需真正的新启动条件。 |
| UWP/WinUI 壳窗口只有标题栏或空 Pane | 核对 ApplicationFrameWindow、原生子窗口及独立内容窗口，查找实际 CoreWindow/内容承载 HWND 后重新 see | 壳为空不证明内容无树；不能跨 PID 仅凭标题猜错对象。找不到承载窗口时记录定位缺口。 |
| 有树但点击/写入无效 | 读取值/状态；比较已授权的 Legacy、Invoke、选择、展开等语义路线；确认真实目标与返回值 | Legacy 是候选路线，不保证所有应用都不夺焦；当前 click 的 Legacy 路由仍在前台权限门之后。某个 setter 静默返回时必须读回或观察实际效果。 |
| 自绘/Canvas/GPU 画面、树无语义控件 | 并行检查无障碍/Legacy、原生子 HWND、应用快捷键、官方自动化接口或导出；截图仅帮助观察 | 不假设当前有坐标点击工具；若需视觉交互而工具未提供，记录缺口或用已授权且确实可用的工具。截图不可用不证明其他通道不可用。 |
| 需要完整长列表/历史记录 | 先检查搜索、展开、分页、滚动、ItemContainer/VirtualizedItem 等 provider 能力，以及应用导出/API | 只尝试实际封装且 provider 暴露的接口；每页验证新增项目并去重。未渲染内容不可从一张截图推断完整。 |
| UI 路线成本高或需要精确数据 | 检查应用已有官方 API、CLI、脚本/自动化接口、导出功能或浏览器语义工具；必要时采用已有合法 CDP 会话 | 这是可选的外部路线，不假装 winmcp 已内置。先核对能力、权限、数据来源与结果；已确认端口不可用时记录限制，不反复猜端口或绕过限制。 |

## Electron 的具体对照条件

open_app(..., accessibility=true) 当前会追加三项：
- --force-renderer-accessibility：历史 QQ 试验用于开启 renderer 无障碍。
- --disable-backgrounding-occluded-windows
- --disable-features=CalculateNativeWinOcclusion
  后两项用于对照后台/遮挡降级；历史 QQ 记录为任意一个可保树，不保证其他版本。

先保存启动前的窗口与参数，再检查新进程是否真的带参数。重新 open_app 不会自动
关闭旧实例，单实例程序可能忽略参数。需要重启时先保护未保存工作并核对已有授权，
不能把自行杀进程当成普通探测步骤。QQ 9→132 等数字只作历史对照，现场记录真实值。

open_app 隐藏的窗口用返回的 hidden_windows 里的 hwnd 定位；windows() 只列可见窗口。
要把隐藏窗口显示出来只能用 reveal(hwnd)，而它**会**接管前台：调用前必须取得用户同意，
且它是唯一应该主动改变用户屏幕的工具。归属未能确认（visibility_control=unconfirmed）
时，候选列表里的窗口不是我们启动的，只能用 windows()/see() 继续定位，不要 reveal 一个
不属于本次启动的窗口。

## 虚拟化列表的采集闭环

先在两页上验证“读当前项→滚动/翻页→界面确实变化→读新增项”能工作，
优先用业务 id 去重；没有业务 id 时说明使用哪些内容字段，不按屏幕坐标去重。
记录访问页数、唯一条目数、滚动位置/边界与完整性依据。出现不变化、循环页、
权限缺失或工具不足时停止并报告 partial，留下未解决项；不能拿屏幕可见行数冒充总数。
若没有可靠的完整性证据，改查导出/API 等路线，或明确结果不完整。

## 已知但未试的方向：保留为假设

- 滚轮/ScrollPattern 在 QQ 路线失败后，可对照 --disable-gpu/软件渲染；
  尚未证明会使滚动生效，可能影响性能与显示，变更前评估并取得所需授权。
- 对照 --disable-features 的其他组合，包括 GPU 合成相关方向；原记录没有可靠的
  具体 feature 名，先查当前应用/运行时文档，不编造参数，也不一次改多项。
- 后台读树异常时，与不带 --force-renderer-accessibility 的裸启动作对照；
  这是验证假设，不是建议默认关闭无障碍；新实例条件、前后台及预算保持一致。

每个实验只改变一个条件，先记录基线、预期观测和回退方式；试完更新 memory，
把结果标为已验证/本环境失败/仍未试，不能把清单从文档删掉就当处理完成。

## 通用入口：什么时候用 invoke_pattern 与 post_message

固定工具（click/type_text/key/scroll）覆盖常见操作；它们解决不了时，用这两个通用入口，
而不是绕开权限或退回盲点。

**invoke_pattern(hwnd, pattern, target, method, args)** —— 读或调用 provider 暴露的
任意已封装 pattern 成员：
- 用于 Value/Text/Selection/ExpandCollapse/Scroll 之外的成员，或需要读公共属性链，
  例如 `DocumentRange.GetText`、`GetSelection`、`GetVisibleRanges`、`IsSelected`。
- 只读成员表内的成员可在后台查询；表外成员（含 SetValue、Invoke、Close、SetFocus
  等可能改状态或夺焦的动作）需要先取得 allow_foreground 授权。
- **不要用 Get 前缀判断安全**：表是显式维护的。某个应用的只读 getter 实测会夺焦时，
  在 memory 里把该路线记成 uses_foreground=true，不要继续当后台方案复用。
- 现状已知的成本：`LegacyIAccessiblePattern` 的 `Name`/`Description`/`Value` 是纯读取，
  但不在只读表内，因此需要 allow_foreground 才能调用（实测：同一窗口内 `Name` 授权后
  返回字符串、`Description` 返回空串）。这是表覆盖面的缺口，不是应用问题；遇到时
  按授权流程走，并把“本应用该用哪个只读接口替代”写进 memory 的未解决/未试方向。
  是否把 Legacy 读取加入只读表属于契约变更，需要同时补测试与副作用证据，不能顺手放宽。
- 定位是纯精确的：AutomationId 或 name 必须唯一命中且树完整，否则
  `no such control` / `ambiguous target` / `tree incomplete`，不动作。
- 返回值已投影成普通数据：TextRange 变成有界文本（`possibly_truncated` 表示已到 API
  上限，与传输截断 `result_truncated` 是两件事），Control 变成元数据。遇到
  `result unsupported` 说明该类型还没有投影——调用可能已经执行，不得自动重试，
  记录这个缺口（需要哪种投影）而不是当成失败路线删掉。
- `pattern not wrapped` 表示当前依赖没有该 pattern 的封装，附带的 pattern_id 就是
  后续补封装的目标；这和“应用没有暴露该 pattern”不是一回事，不能混成应用不支持 UIA。

**post_message(hwnd, msg, ...)** —— 原生窗口消息：
- 查询状态用 `wait=true`（SendMessageTimeoutW），带 child HWND 和具体消息；
  `WM_GETTEXTLENGTH`、`BM_GETCHECK`、`CB_GETCURSEL`、`LB_GETCURSEL` 是典型查询。
- 异步投递用 `wait=false`（PostMessageW）。响应只有 `queued`，没有 result：
  消息还没到目标，之后仍可能改变窗口。
- 文本走托管路径：`WM_GETTEXT`/`WM_SETTEXT` 由服务分配缓冲区，绝不传指针；
  `WM_SETTEXT` 会在同一时间预算内读回比较，`text readback mismatch` 才算写入不符，
  `readback unavailable`/`budget exhausted` 只说明本次无法验证。
- 广播句柄、`WM_COPYDATA`、`WM_DROPFILES`、同进程窗口一律拒绝；未知标量需要
  allow_unsafe + 前台授权，且调用方须自己确认该消息不携带指针或句柄。
- 鼠标消息的参数是 Win32 约定：按钮消息 lparam 用客户区坐标，滚轮 lparam 用屏幕坐标、
  wparam 高字是带符号滚动量。截图得到的坐标要先换算。

## 效果验证、超时与知识回写
查询保存真实 result/text；写入用读回；点击用目标状态/反馈；滚动用位置和项目变化。
call_completed、queued、returned 都不自动代表业务完成；provider 返回 False 时
按具体方法语义处理。worker 或消息超时为 execution_state=unknown，先读目标现状，
不自动重发可能已执行的动作；busy/not_started 才能按明确未执行处理。

用 remember 写 Markdown body，必须包含下列八个二级标题；安装后无需额外交接文件：
- `## 目标`：任务和可观测完成标准。
- `## 环境与适用条件`：日期、实际版本及来源、exe、启动参数、窗口前后台/可见状态、
  winmcp/依赖版本；缺失字段写未记录，不补猜。
- `## 已验证步骤`：逐步工具、实际参数、返回值、效果验证与光标/前台副作用。
- `## 已尝试但失败`：输入、观测/错误、环境、失败范围；一次失败不推广到所有版本。
- `## 实测记录`：计数/耗时/像素变化的原值、样本/统计口径及日志/截图位置；
  历史转录与本次新测分开，冲突数据并列。
- `## 未解决`：能力缺口、影响的目标、已试到哪里、下一步需要什么。
- `## 未试方向`：标未验证，写思路依据、对照步骤、预期观测、代价与回退；
  权限未满足、工具缺失、已试失败分别记录，没有内容写尚未记录。
- `## 更新记录`：新增、修正、证伪及旧结论的适用范围变化。

覆盖前先读完整旧正文并合并；保留失败与未试路线，不能只写最新的成功结论。
未知副作用填 uses_foreground=true，新方案 rank=0。版本仍未知时传 version=None，
记录为 app@unversioned，明确告知用户尚未归属实际版本，不丢弃本次探索报告。
未定版本记录不得升为 reviewed/proven；确认实际版本后另建本版本记录再验证。
用户明确确认 key/id 与内容后再 approve(expected_revision=原摘要)；有多次成功记录
并取得确认后再 confirm_proven。stale plan 重新读取确认，不悄悄刷新摘要继续审核。

## 随 skill 携带的历史起点（不是本次测量）

以下转录自仓库基线 abb55bd 的设计/交接稿与 README，原始请求和性能日志未保留。
不依赖安装目录外的文件才能理解这些方向；新任务仍需记录自己的环境和结果：
- QQ 原交接稿报告无 flag 为9节点/0命名；a11y前台及有防降级flag后台为132/130，
  无防降级后台为0/0。README另报128/126，口径不同，均不能作现场固定节点数。
- QQ Legacy点击当时有效且未观察到夺焦；Invoke当时无效并夺焦；给渲染宿主投递
  LBUTTON当时无效。不能只按调用耗时或 API 返回选择路线，仍需核对效果。
- QQ 滚轮当时像素变化为0，Notepad对照为7367，算法/参数未留；ScrollPattern报告
  COMError/VerticallyScrollable=False；1980人名单未收全。此处的失败保留为现场限制，
  上文GPU/其他features/裸启动仍是未试假设，不能据此判断所有软件都滚不动。
- QQ FileVersion曾为9.9.19.35469，而安装候选目录为9.9.22-40824；候选目录不能
  替代活动exe证据，不因看到更高版本目录就把别的版本信任位套到当前进程。
