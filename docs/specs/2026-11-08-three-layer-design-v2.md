# winmcp 三层框架设计（重写版）

日期：2026-11-08
状态：待审批
上一版：2026-11-08-three-layer-design.md（已被本文件取代）

## 0. 这一版改了什么

上一版经独立审阅提出 34 条问题，其中 9 条阻塞实现。核实后重写，主要变化：

| 上一版 | 这一版 | 理由 |
|---|---|---|
| 声称"QQ 结论只活在对话里" | 承认 INSTRUCTIONS / README 已有散文结论 | 事实错误。真正缺的是**机器可寻址、带版本**的结论 |
| index.json 独立文件 | **方案文件 frontmatter 为唯一真相**，索引每次扫描生成 | 消灭双源矛盾：共享方案时 frontmatter 的 index 字段必然对其中一条是错的 |
| 插件层可插拔 | **推迟，不进 MVP** | 不可达（只列不执行）、不安全（任意 Python 进主进程）、契约空白 |
| 四态 status | **两态 + reviewed 布尔** | `blocked` / `needs-tool` 先写进 body 的"未解决"，不需要状态机 |
| 缺版本探测 | **新增 `app_info()` 工具** | 没有它，`recall("app@version")` 拿不到 version，skill 第一步就是死锁 |
| 没有通用逃生口 | **新增 `invoke_pattern()` / `post_message()`** | skill 探出新 pattern 必须能发出去，否则 §2 的能力承诺是假的 |
| 索引整个注入 | **recall 必须带 query**，永不返回全表 | 实测 45 条索引 ≈ 1086 tokens ≈ 4k 上下文的 26.5% |
| gaps.json 独立 | **由 `needs-tool` 派生** | 一个文件、一个字段，天然有 join key |
| 用 `requires: [open_app(a11y)]` | **自由文本 + 可选结构化** | 实测 `a11y` 不是真参数名、`legacy` 是内部路由决策，机器无法判定 |

## 1. 为什么做这个（修正后）

winmcp 现在有 8 个可用原语，但**每遇新软件都从零摸索**。QQ 这一轮的代价：试 OCR → 试 UIA（读到 9 个空节点）→ 试 CDP（端口封）→ 加 a11y flag（132 元素）→ 误判为"重启失效"（实为失焦归零）→ 找到两个 flag → 发现点击抢前台 → 试三种点击 → 落到 LegacyIAccessible。

**这些结论现在分散在三处，且都不是机器可寻址的：**

- `server.py` 的 `INSTRUCTIONS`：散文，随版本手改，无版本号
- `README.md`：散文，面向人
- 本次对话：会丢

真正缺的不是"把结论写下来"，是**让 agent 能按「软件 + 版本」精确查到它**，并且知道这条结论**在哪个版本上被验证过**。

## 2. 三层职责

```
skill      探索策略：陌生软件怎么下手、失败路径、未试方向
  │
  ▼
memory     已探明结论：方案 md（frontmatter 为唯一真相）+ 按需 recall
  │
  ▼
mcp        执行原语：现有 8 个 + 3 个新逃生口
```

闭环：mcp 越全 → skill 能探越多 → memory 越厚 → 下次越少摸索 → memory 记下缺口 → 反过来推 mcp 演进。

## 3. memory 设计

### 3.1 目录

```
%LOCALAPPDATA%\winmcp\memory\
  playbooks\
    qq-app.md
    vscode.md
```

位置通过 `WINMCP_MEMORY_DIR` 覆盖，默认如上。不存在时 `recall` 返回空、`remember` 自动创建。

**不放 repo 里**：这是本机事实（软件版本、路径、用户设置），进 git 会和代码版本纠缠。

### 3.2 方案文件格式（唯一真相）

一个 key 对应一条记录，记录里挂一个**方案列表**——同一软件常有多条路径，各有取舍。

```markdown
---
key: QQ@9.9.22
app: QQ
version: 9.9.22
updated: 2026-11-07
verified_with: winmcp 0.1.0
plans:
  - id: B
    summary: 不抢前台，读树约 1.5s
    cost: 比强前台慢约 30 倍
    uses_foreground: false
    reviewed: true
    proven: true
    body: plans/qq-B.md
  - id: A
    summary: 强前台，约 50ms，最快
    cost: 抢走光标并改变前台，会打断你
    uses_foreground: true
    reviewed: true
    proven: false
    body: plans/qq-A.md
---

## 未解决
滚动采集：滚轮 0 像素变化，ScrollPattern 报
VerticallyScrollable=False。1980 人群成员无法拉全。
```

**三个字段，两个维度 + 一段取舍说明：**

| 字段 | 含义 | 性质 |
|---|---|---|
| `reviewed` | 人看过并认可 | 主观判断 |
| `proven` | 多次实战跑通过 | 客观事实 |
| `summary` + `cost` | 这条方案快不快、代价是什么 | 供 agent 按情境选 |

**排序 `11 > 01 > 10 > 00`**：先看 `proven`（客观），再看 `reviewed`（主观）。

数字编码 `proven*2 + reviewed`，即 3 > 2 > 1 > 0。

理由：一个没经人审核但已跑通二十次的方案，比一个只被瞄了一眼的方案更可信。

**`00` 的处理**：排序最后不等于永不使用。`00` 方案被选中时必须先按 skill 的探测流程验证，不能直接照做。这条要写进 skill，否则 agent 会把 `00` 当普通方案执行。

### 3.2.1 为什么 `cost` 和 `uses_foreground` 必须分开

`cost` 是给人看的散文，`uses_foreground` 是给 agent 做硬判断的布尔值。

实测场景：用户正在用电脑时，即使某方案排 `11`，只要 `uses_foreground: true` 就必须排除——抢前台会打断用户，这是产品唯一承诺的红线。只靠 `cost` 里的文字描述，agent 可能理解不到位；一个布尔字段让它无法绕开。

### 3.3 版本共享的正确做法

若 9.9.19 和 9.9.22 行为一致：

- `qq-9.9.22.md` 写完整方案，`status: verified`
- `qq-9.9.19.md` 只写 frontmatter + 一行 `see: qq-9.9.22.md`，`status: unverified`

`recall` 遇到 `see:` 会跟随一次并标注"继承自已验证方案，本版本未单独验证"。

这样既避免重复，又不会把 A 版本的 verified 冒充成 B 版本的。

### 3.4 状态不再是一个字段

上一版的 `status: verified | unverified` 已废弃，改由每个 plan 的 `reviewed` / `proven` 两布尔表达：

| reviewed | proven | 编码 | 含义 |
|---|---|---|---|
| 1 | 1 | `11` | 人都认可、且多次跑通 |
| 0 | 1 | `01` | 跑通过但人没审过 |
| 1 | 0 | `10` | 人看过认可，但只跑过一次 |
| 0 | 0 | `00` | 新探明，两条都不满足 |

被封 / 需要新工具的情况**不设状态**，写进 body 的「未解决」段落，由 `recall` 原样返回。

`proven` 何时置位：由 agent 在同一 key 上成功执行达 N 次后建议置位，**需用户确认**。MVP 阶段先手工填，不自动计数——自动计数容易把"碰巧成功"记成"稳定可行"。

### 3.5 缺口：派生，不另存

`gaps()` 扫描所有方案，收集 body 里以 `## 未解决` 开头的段落，返回：

```json
[{"key": "QQ@9.9.22", "text": "滚动采集：滚轮 0 像素变化…"}]
```

没有独立文件、没有 id、没有关闭状态——那条段落被删掉，缺口自然消失。上一版设计的三处（gaps.json、status=needs-tool、recall 返回缺口）在这里合成一处。

## 4. MCP 工具

现有 8 个不变。新增 3 个：

### 4.1 `app_info(hwnd_or_pid)`

**解决版本死锁。** 返回：

```json
{"name": "QQ", "version": "9.9.22", "source": "program_dir",
 "exe": "C:\\Program Files\\Tencent\\QQ.exe",
 "file_version": "9.9.19.35469", "product": "QQ", "company": "Tencent"}
```

**版本来源优先级（已实测，不能用错）：**

1. **程序目录名** —— `<install_dir>\versions\` 下的形如 `9.9.22-40824` 的目录，取 `-` 前的部分。QQ 实测得 `9.9.22`。
2. **回退 FileVersionInfo** —— 取前两段。但 QQ 实测是 `9.9.19.35469`，前两段只有 `9.9`，**和目录名对不上**。

实测对照：

| 来源 | QQ 的值 |
|---|---|
| FileVersion | `9.9.19.35469` |
| 程序目录 | `9.9.22-40824` |
| 取前两段 | `9.9`（错误，丢失 .22） |

所以：**有 versions 目录就用目录名，且要取完整的三段**（不是前两段）。没有 versions 目录的程序，才回退 FileVersion 取前两段，并在返回里标 `source: "file_version"`，让调用方知道这个版本号可信度较低。

`versions` 目录下还有 `channel.json` / `config.json` / `setting.json` 等非版本文件，必须用正则 `^\d+(\.\d+)+(-\d+)?$` 过滤。这条也要写进实现——上一版没写，实测时就被 `setting.json` 干扰了。

### 4.2 `invoke_pattern(hwnd, name, pattern, args)`

通用 UIA 模式调用。`pattern` 是 `Control.GetPattern` 能接受的任意名称，如 `SelectionPattern2`、`TextPattern`、`ExpandCollapsePattern`。

理由：现在 act.py 只有 6 个硬编码 pattern，skill 探出新 pattern 无处可发。实测 `Control.GetPattern()` 存在，成本低。

返回沿用项目约定 `{ok, route, reason?, detail?}`，`route: "uia:<pattern>"`。

### 4.3 `post_message(hwnd, msg, wparam, lparam)`

向窗口发任意 Win32 消息。这是 skill 探索 BM_CLICK / WM_SETTEXT 之外的任何消息的出口。

**风险必须写明**：任意消息可以关窗口、改状态。所以：

- 默认只允许白名单消息（BM_*, WM_* 无害子集），名单外需 `allow_unsafe=true`
- 返回里必须带 `foreground_changed`
- 文档里明确：这是探索工具，不是日常工具

### 4.4 `recall(query)`

```json
{"query": "QQ"}                        // 返回到所有版本
{"query": "QQ@9.9.22"}                 // 精确
```

匹配规则（上一版完全空白，这里定死）：

1. 含 `@`：精确匹配 key；未命中则**回退到同 app 家族**并标注 `exact: false`
2. 含 `.exe` 或路径：用文件名匹配 app
3. 否则：app 名不区分大小写的子串匹配
4. 永远不返回全表；单条方案超过 6000 字符时截断并给 `truncated: true`

返回：

```json
{"matches": [{
   "key": "QQ@9.9.22",
   "plans": [
     {"id": "B", "summary": "不抢前台, ~1.5s", "cost": "慢 30 倍",
      "uses_foreground": false, "reviewed": true, "proven": true,
      "rank": 3, "body": "## 步骤 ..."},
     {"id": "A", "summary": "强前台, ~50ms", "cost": "打断用户",
      "uses_foreground": true, "reviewed": true, "proven": false,
      "rank": 1, "body": "## 步骤 ..."}
   ],
   "unresolved": "滚动采集：滚轮 0 像素变化…",
   "inherits": null,
   "truncated": false
 }],
 "exact": true}
```

**plans 按 rank 降序**，agent 拿到的第一条就是默认推荐。同时每条都带 `uses_foreground`，让它能做硬过滤。

### 4.5 `remember(...)`

```json
{"app": "QQ", "version": "9.9.22",
 "plan": {
   "id": "B",
   "summary": "不抢前台，读树约 1.5s",
   "cost": "慢 30 倍",
   "uses_foreground": false,
   "body": "## 步骤\n1. open_app(...)\n..."
 }}
```

- 默认写 `reviewed: false, proven: false`
- 已存在同 key 同 plan.id 时**返回冲突**，需 `overwrite=true`
- 往已有 key 添加新 plan 而不覆盖：`append=true`
- 原子写（临时文件 + rename）
- 返回 `{ok, path, plan_id, rank}`

**审核与实战确认是独立操作**，不塞进 remember：

```json
{"approve": {"app": "QQ", "version": "9.9.22", "plan": "B", "reviewed": true}}
{"confirm_proven": {"app": "QQ", "version": "9.9.22", "plan": "B"}}
```

两个分开，因为它们是不同性质的动作：批准是人事先认可，实战确认是事后追加的证据。合成一个参数会让人分不清自己确认的是哪个。

### 4.6 错误约定

全部沿用现有形状：`{ok: false, reason, detail, hint?}`。`recall` 未命中返回 `{ok: true, matches: [], exact: false}`——**"没找到"不是错误**。

## 5. skill 层

新增 `windows-app-automation`，装在 DSH 的 skills 目录（`~/.dsh/skills/`），Claude/Codex 通过已有 junction 机制共享。

内容（**这是整层价值所在，所以写具体**）：

```markdown
## 探测顺序（遇到陌生软件按此走，不要跳步）

1. app_info(hwnd) 拿 name + version
2. recall("name@version")
   - 命中 verified + reviewed: true → 照做，跳过探测
   - 命中 reviewed: false → 照做但每步验证
   - 未命中 → 继续
3. see(hwnd, with_tree=true)
   - 树非空且命名控件多 → 走 UIA 路线
   - 树是空 PaneControl 壳 → 记录"疑似 Chromium/Electron"，转 4
4. 若疑似 Electron:
   重新用 open_app(..., accessibility=true) 启动
   - 树变丰富 → 成功，记住
   - 仍为空 → 记录"a11y 无效"，继续 5
5. 视觉兜底 see() 截图
   - 注意：虚拟化列表屏幕外不存在，视觉只能看可见行
6. 全部失败 → 写 remember，body 的「未解决」写明试过什么

## 未试方向（已知但没验证，探到时优先试）

- 滚轮无效时可试 --disable-gpu 强制软件渲染，但会明显降性能
- --disable-features 的其他组合（含关 GPU 合成）
- 后台读树失败的窗口，可试不带 --force-renderer-accessibility 的裸启动对照

## 写记忆

探明后调 remember(...)，新方案记为 00（reviewed: false, proven: false）。
告诉用户"已记录，编号 00（未审核、未实战验证）"。

## 选方案（同 key 有多个 plan 时）

1. 先把 reviews/proven 算成 rank（proven*2 + reviewed），降序看
2. **用户正在用电脑**：立刻排除 uses_foreground: true 的全部方案，
   哪怕它 rank 最高。抢前台是唯一红线。
3. 剩多个时比 cost：要快要准还是要不打扰
4. 选中的是 rank 0（00）时：**先按上面的探测顺序验证一遍**，
   通过了再照做，不要直接执行
5. 用户离开时可用强前台方案，但要先说"这会占用屏幕"
```

**审查者指出 skill 是静态文档、无法积累"未试方向"** —— 这条成立但**不该由 skill 解决**。未试方向属于"知识"，应该进 memory（body 的「未解决」段落），skill 只规定"要去查、要往回写"。这样 skill 保持静态、不会漂移。

## 6. 不做的事

- **不做插件层**（推迟）。理由见 §0。
- **不做全自动记忆**：写盘只发生在 agent 主动调 `remember`。
- **不做跨机器同步**。
- **不做方案库浏览 UI**：`recall` 足够了；要列全，用 `recall("")` 返回 app 名列表（不含正文，约 20 tokens/app）。
- **不碰 ScreenHand 的代码**：TypeScript + .NET，语言不通，借设计不借代码。

## 7. 验收标准（每条都可判）

| # | 标准 | 判定方式 |
|---|---|---|
| 1 | `app_info` 能返回 QQ 的正确版本 | 实测已确认：目录名 `9.9.22` vs FileVersion `9.9.19`；断言返回 `9.9.22` 且 `source == "program_dir"` |
| 2 | `invoke_pattern` 能调用 act.py 里没有的 pattern | 用 `ExpandCollapsePattern` 在一个真实窗口上验证 |
| 3 | `post_message` 白名单外需显式允许 | 传入非白名单消息，确认被拒 |
| 4 | `recall` 精确/家族/未命中三种行为正确 | 三条断言 |
| 5 | `remember` 原子写、冲突检测、默认 `00` | 三条断言 |
| 6 | 一个 key 挂多个 plan，按 rank 降序返回 | 造两条方案验证顺序为 3,1 |
| 7 | `uses_foreground: true` 的方案在用户忙碌时被 skill 排除 | 断言 skill 文本含此规则 + 排序测试 |
| 8 | `00` 级方案必须先验证才能执行 | 断言 skill 写明此规则 |
| 9 | 同版本继承（`see:`）能工作且标注 | 造两个文件验证 |
| 10 | **现有 36 项自检全部通过** | `python -m winmcp.check` |
| 11 | **新增能力都有自检**，并入 check.py | 新增断言数 > 0 |

排序规则本身已用独立脚本验证通过（`11 > 01 > 10 > 00`，且用户忙碌时能排除抢前台的方案），实现时照此写断言即可。

## 8. 风险

| 风险 | 缓解 |
|---|---|
| `post_message` 发任意消息可以搞坏应用 | 白名单 + 显式放行 + 返回值必带副作用报告 |
| version 取错导致 key 全错 | 实测 QQ 两种来源不一致，优先目录名，并写自检 |
| memory 与 INSTRUCTIONS/README 三处漂移 | 明确分工：INSTRUCTIONS 讲通用规则，memory 讲具体软件版本，README 讲人看的背景 |
| 探索策略写得再全，agent 也可能不读 | skill 描述要短、触发词要准（"不认识这个软件"） |
| 框架比工具重 | MVP 只加 3 个工具 + 2 个 memory 工具 + 1 个 skill |
