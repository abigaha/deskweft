# DeskWeft 收口执行计划

日期：2026-11-09。基线：`master` @ `9f926aa`。
依据：`docs/specs/2026-11-08-implementation-handoff.md`（契约）、
`docs/specs/2026-11-08-three-layer-design-v2.md`（理由）、
`docs/reports/2026-11-08-qq-wechat-live.md`（现场证据）。

本计划覆盖 A/B/C/D/E 五组共 20 项。每项都写明：现状证据、要做什么、怎么验、完成的
判据。不做没有验收动作的条目。

## 0. 已完成的前置（不在计划内，仅记录）

- 移除部署副本 `%LOCALAPPDATA%\deskweft\deskweft\`（已移到
  `deskweft.copysnapshot-20261109-132121`）。部署 venv 原先装的是 wheel 快照，
  已改为 editable 指向仓库；服务重启后加载仓库代码，17 工具在线。
- 结论：此后 `site-packages` 与 cwd 都不再持有代码副本，仓库是唯一真相。

## 1. 全局约束

- 每个代码改动先写失败测试，再实现，再跑全套。
- 任何真实 GUI/应用操作只在明确授权的范围内进行；用户桌面上的应用不擅自重启、
  不擅自点击。
- 文档必须区分"已验证/已试失败/未试/工具缺口"，不得把提议写成实测。
- 涉及真实 provider 的条目，若当前环境无法安全复现（如需重启应用、需要扫码登录），
  则该条目的"实现"与"现场验收"分开记录：实现完成并离线验证，现场验收标为未执行
  并写明原因。

## 2. 优先级与依赖

```
P0 (正确性/安全，先做)
  A1 坐标点击遮挡校验 ──┐
  A3 SendKeys 首字符    ─┴→ 都依赖"焦点/像素归属"这一层，先做 A1
  A2 微信假报成功 → 影响 skill + memory 的判断规则

P1 (交付完整性)
  B2 服务验证 ──→ 依赖 0 已完成（服务已在仓库代码上运行）
  B1 改名后 GUI 自检

P2 (能力缺口，按价值排序)
  C1 Control 输入适配
  C4 微信主界面语义（可能无法在不改应用的前提下实现 → 保留缺口）
  C2 QQ 联系人列表
  C6 SetValue 调用前保护
  C3 微信后台路线
  C5 私有 desktop 可视/接管

P3 (对照实验，需要重启应用/改启动参数 → 需单独授权)
  D1 --disable-gpu
  D2 其他 --disable-features
  D3 裸启动作对照
  D4 QQ CDP

P4 (文档)
  C7 稳定性表述
  E  新事实写入 skill/memory
```

---

## A. 真实缺陷

### A1. 坐标点击遮挡校验（P0）

**现状**：`deskweft/act.py:411` 与 `:466` 直接用元素矩形中心 `SetCursorPos` + `Click`，
不检查该像素归属。2026-11-09 实测因此误点到被遮挡的另一应用窗口。

**要做**：
1. 新增 `win32.window_at(x, y)`：`WindowFromPoint` + `GetAncestor(GA_ROOT)`，返回根 HWND。
2. 新增 `act._assert_reachable(hwnd, x, y)`：像素根 HWND 必须等于 `hwnd`，否则返回
   结构化失败 `{"ok": false, "reason": "target obstructed", "detail": ...}`，
   `execution_state="not_started"`，且不移动光标。
3. 在两处真实鼠标路径调用前插断言。断言失败不发 `SetCursorPos`、不发 `Click`。
4. 元素矩形本身还要满足：宽高 > 0、中心点落在窗口客户区内（用 `GetClientRect` +
   `ClientToScreen` 换算，避免点到非客户区）。
5. 中英文注释说明这是与"不点窗口中心"同级的拒绝规则。

**测试**（`tests/test_act.py` 新增）：
- 遮挡时：`reason == "target obstructed"`，`SetCursorPos`/`Click` 调用次数为 0。
- 未遮挡时：正常点击，且坐标等于换算后的客户区中心。
- 无矩形/零矩形仍返回 `control has no clickable area`。
- `window_at` 本身：给一个假 HWND 返回不匹配；给真实自身窗口返回自身。

**完成判据**：4 条测试由红转绿；全套通过；`act.py` 两处路径都有断言。

---

### A2. 微信 UIA 假报成功（P0，文档+行为）

**现状**：实测 `LegacyIAccessiblePattern.DoDefaultAction` 与 `InvokePattern.Invoke`
对微信"进入微信"按钮均返回 `True`、`execution_state=completed`，界面无变化；
真实鼠标点击才生效。报告未记录。

**要做**：
1. **不改**工具返回契约（`effect_verified=false` 已经正确表达"只拿到结果"）。
2. 在 `act._click_uia` 增加可观测的补充：动作类成员返回成功但**随后可读回状态未变**
   时，在结果里加 `observation="no visible change detected"`（仅当能廉价读到该控件
   的状态或名称时；读不到就不加，不做假判断）。
3. `skills/windows-app-automation/SKILL.md`：在"有树但点击/写入无效"行补微信实例，
   写明两个语义路线都假报成功、必须用真实鼠标或换通道验证。
4. 用 `remember` 写入 `weixin@4.2.0.13` 一条新 plan（`uses_foreground=true`，
   正文含八段，`## 已尝试但失败` 记录这两条，`## 未解决` 写主界面无语义）。

**测试**：`test_act.py` 新增"动作返回 True 但状态未变"分支，断言
`observation` 字段存在且 `effect_verified` 仍为 false。

**完成判据**：测试绿；skill 段落更新；memory 写入并用 `recall` 读回核对 revision。

---

### A3. SendKeys 首字符丢失（P0）

**现状**：实测 `AAAA...` 首字符丢失，`DeskWeft` → `. eskWeft`。`act.py:468`
点击后只 `sleep(0.12)`；`key` 路径 `:546` 直接发。

**要做**：
1. 抽出 `_type_after_click(x, y, text)`：点击 → 等待焦点稳定 → 清空 → 输入。
   焦点稳定判据不用固定 sleep，而是：
   - 轮询 `GetGUIThreadInfo(foreground_thread).hwndFocus` 直到非空，最多 N ms；
   - 再等一个短稳定期（如 100ms）让输入法切换完成。
2. 清空改为"选中全部后按 Delete"，且在键入前**验证控件为空**（能读回时）；
   读不到就不宣称清空成功。
3. 若首个字符仍可能丢，改为**先发一个无副作用的前导键**（如 `{RIGHT}`）再发正文，
   并在注释说明理由；该行为必须有测试。
4. `key` 路径同样接入焦点轮询。

**测试**：
- 焦点轮询：`GetGUIThreadInfo` 依次返回 `hwndFocus=None`、`None`、`hwnd`，
  断言最终在拿到非空前才开始发键，且总等待不超过上限。
- 前导键：断言发送序列为 `["{RIGHT}", text]`（若采用该方案）。
- 超时：焦点始终为空 → 返回 `target not focused`，不发送正文。

**完成判据**：测试绿；真实应用上重测一次，首字符不丢（记录在报告）。

---

## B. 交接稿留白

### B1. 改名后 GUI 自检（P1）

**要做**：
1. `deskweft/check.py` 内所有 `winmcp` 字样改为 `deskweft`（若有残留）。
2. 在确认安全的会话运行 `python -m deskweft.check`，记录完整输出。
3. 任何 FAIL 按缺陷修，不跳过。

**完成判据**：自检全绿；输出摘要写入报告；SKIP 项必须写明原因。

---

### B2. 已安装 8765 服务验证（P1）

**现状**：服务在跑，17 工具在线，但只验证过工具清单与 `forget` 闭环。

**要做**（全部只读或自建窗口）：
1. 真实 HTTP 调用 `windows()`：返回列表非空、字段齐全。
2. 真实 HTTP 调用 `see(hwnd=<自建测试窗口>)`：验证文本块 + image 块形状、
   `foreground_*` 字段在 meta 里。
3. 真实 HTTP 调用 `see(hwnd=0)`：验证在 provider 前返回 `invalid arguments`、
   `execution_state=not_started`。
4. 真实 HTTP 调用 `app_info`：对一个已知应用返回 `source` 与 `version`。
5. worker 回收：连续 3 次 `see` 后，检查子进程数不增长；`close` 后无残留（用
   进程快照在测试进程内验证，不依赖服务端日志）。
6. 生命周期：确认服务端通过 FastMCP lifespan 的 finally 调 `uia_worker.close`
   （停服务时子进程消失）。

**完成判据**：6 项各有实际输出；写入报告。

---

## C. 能力缺口

### C1. Control 输入适配（P2）

**现状**：`invoke_pattern` 的 `args` 只接受 JSON 标量，拒绝 null 与 Control 字典；
只有 `find_items` 做了 NULL 首轮与同调用续项托管。

**要做**：
1. 不改 `invoke_pattern` 的 args 约束（契约要求）。
2. 为需要 Control 入参的常用方法提供**专用托管工具或参数**：先做
   `ItemContainerPattern.FindItemByProperty` 已覆盖的续项；再评估
   `TreeWalker`/`GetItem(row,col)` 等是否需要。
3. 若某方法无法安全托管，写进 §4.3 的"已知缺口"表，并在 skill 里写明可替代路线。

**完成判据**：至少新增一个专用适配（含测试）；其余明确列为缺口，有 skill 指引。

---

### C2. QQ 联系人列表未取得（P2）

**现状**：四次 ItemContainer 探测全 `pattern unavailable`，未收全。

**要做**：
1. 用 `find_items` 在 QQ 联系人/群成员页重试，记录 `pattern_id`、`cause_unknown`、
   `provider_calls`、`complete`。
2. 若仍不可用，改用 `ScrollPattern` + 分段读树，并记录每页唯一项与去重依据。
3. 都失败则明确记录"当前版本该容器不提供 ItemContainer"，不宣称 QQ 无法自动化。

**完成判据**：一条可复现的结论 + 原始参数与返回值；写入 memory。

---

### C3. 微信后台路线（P2）

**现状**：只有独立 COM/MSAA 只读调查，未取得会话内容。

**要做**：按报告保留的范围继续只读调查：子窗口根、MSAA、短 listener。
本计划**不**承诺取得会话内容；目标是给出"能读到什么、读不到什么"的明确边界。

**完成判据**：一份只读矩阵（目标 × 方法 × 结果），失败处写明原因类别。

---

### C4. 微信主界面无 UIA 语义（P2，可能不可修）

**现状**：登录页 28 元素可读；登录后主界面只有 2 个 Pane。

**要做**：
1. 确认不是过滤导致：用 `read_detailed` 看 `filtered_anonymous`/`filtered_offscreen`。
2. 检查登录后是否换成了另一套渲染窗口（新 HWND/新子窗口）。
3. 若确实无 UIA，则如实记录为**应用侧限制**，并在 skill 里给出可替代路线
   （快捷键、文件传输助手、官方导出）。

**完成判据**：有证据的结论；若无法修，明确写"不建议对微信主界面使用 UIA 定位"。

---

### C5. 私有 desktop 可视/接管（P2）

**现状**：只有 JSON 证据，无预览面板或 `SwitchDesktop`。

**要做**：报告已把它列为候选。本计划只做**可行性验证**：
1. 在私有 desktop 中对目标窗口 `PrintWindow` 截图，验证图像非空、尺寸正确。
2. 若可用，提供一个只读预览脚本（随 skill 交付），不接 `SwitchDesktop`。

**完成判据**：截图可用或明确记录"该 desktop 下 PrintWindow 不可用"。

---

### C6. SetValue 调用前保护（P2）

**现状**：`LockSetForegroundWindow` 尝试 `acquired=false, error=5`；报告称无可靠保护。

**要做**：
1. 复现失败原因（权限/时机/调用顺序），记录 error=5 的真实含义。
2. 尝试替代保护：`AllowSetForegroundWindow`、worker 在私有 desktop 内执行。
3. 若仍无保护，保持"SetValue 标 uses_foreground=true，不从后台重试"的规则，
   并在 skill 的决策表里固化。

**完成判据**：要么有可验证的保护（含失效检测），要么明确写"无保护，禁后台调用"。

---

### C7. 跨版本/统计稳定性（P4，表述问题）

**要做**：在报告与 skill 中把单轮样本的结论统一表述为"该版本该次观测"，
不写"稳定"、"普遍"。列一张"证据强度"表。

**完成判据**：文档无越界表述。

---

## D. 未试方向（P3，需要重启应用 → 单独授权）

四项都需要改变启动条件（新进程/新参数），因此**必须逐项取得用户授权**，
并在每项前确认：未保存工作、运行中实例、回退方式、只改一个条件。

- **D1** `--disable-gpu` / 软件渲染：对照滚动与后台读树是否变化，记录性能代价。
- **D2** 其他 `--disable-features` 组合：先查当前应用文档，不编造 feature 名，一次只改一项。
- **D3** 裸启动对照（不带 `--force-renderer-accessibility`）：与带 flag 样本同条件对比。
- **D4** QQ CDP：先确认端口与启动命令，历史"端口被封"无日志，需重新核实。

每项完成后写入 memory，标明"已验证/本环境失败/仍未试"。

**完成判据**：每项有实际参数、观测、结论；未获授权的项写明"未执行"。

---

## E. 新事实写入（P4）

已取得的四条事实需进 skill 与 memory：

1. 微信带 `accessibility=true` 启动后**登录页 UIA 完整可读**（28 元素、含 AutomationId），
   与报告"1 个 Pane"不矛盾——那是主界面。→ 写进 skill 的 Electron/Qt 段落。
2. `Selector` 组合消歧在真实微信有效（字符串 `进入微信` 歧义 → `{name,control_type}` 命中）。
   → 写进 skill 的定位段落，作为"同名多控件"的标准解法。
3. `open_app` 归属机制在真实微信正确（10 窗口全 `direct_process`/`observed_descendant`，
   0 误碰）。→ 写入报告作为归属机制的实证。
4. 消息确实送达文件传输助手。→ 写入报告（不含聊天内容）。

**完成判据**：skill 段落更新；memory 有对应 plan；报告有日期与条件。

---

## 3. 执行顺序（分批交付）

| 批次 | 内容 | 产出 |
|---|---|---|
| 批 1 | A1、A3 | 代码 + 测试；真实应用重测 |
| 批 2 | A2 | 代码 + skill + memory |
| 批 3 | B1、B2 | 自检输出 + HTTP 验证记录 |
| 批 4 | C1、C4、C2 | 适配/结论 + memory |
| 批 5 | C6、C3、C5 | 结论或缺口记录 |
| 批 6 | D1–D4 | 需授权后执行 |
| 批 7 | C7、E | 文档收口 |

每批结束：全套测试通过 + 提交 + 更新报告。

## 4. 无法承诺的部分

- C4 可能受应用实现限制，只能记录不能修。
- D1–D4 需要重启用户应用，是否执行取决于授权时机。
- C6 的"可靠调用前保护"可能需要进程/desktop 隔离，超出当前工具范围。
- 任何"稳定/普遍"的结论都不由本轮单样本支持。
