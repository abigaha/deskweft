# winmcp 三层框架设计：skill / memory / mcp

日期：2026-11-08
状态：待审批

## 1. 为什么做这个

现有 winmcp 是一组好用的原语，但每遇到一个新软件，agent 都要从零摸索一遍。这两天在 QQ 上的经历说明了代价：

- 先试截图 OCR，发现群成员列表看不全（虚拟化列表屏幕外不存在）
- 再试 UIA，读到 9 个空节点（Chromium 无障碍树没开）
- 试 CDP，端口被封
- 加 `--force-renderer-accessibility` 重启，读到 132 个元素
- 发现失焦就归零，以为要重启，其实是后台降级
- 找到两个 flag 解决
- 又发现点击抢前台，试了三种点击方式，最后发现 `LegacyIAccessible` 不抢

**这些结论现在只活在这次对话里。** 下次换个软件、甚至同一个 QQ 换个版本，同样的路要再走一遍。

目标不是"让 winmcp 支持 QQ"，是**让这类探索只做一次**。

## 2. 三层各自解决什么

```
skill      探索策略：遇到陌生软件怎么下手，包括失败路径和未试方向
  │
  ▼
memory     已探明结论：按「软件@版本」索引，指向方案 + 所需工具 + 状态
  │
  ▼
mcp        执行原语：能带任意参数启动、读树、发任意 UIA 模式、发任意窗口消息
```

三者是闭环，不是三个零件：

- **mcp 越全**，skill 能探的越多
- **skill 探得越多**，memory 越厚
- **memory 越厚**，下次越不用从零摸索
- **memory 记下"现有 mcp 做不到"的缺口**，下一轮 mcp 就有了明确的待办

## 3. 关键设计决策

### 3.1 memory 存的是「方案 + 它需要的工具」

方案不只是一段说明。它记录了完成这件事**需要哪些工具**，以及当时**工具够不够**：

```markdown
---
index: QQ@9.9.22
kind: app
status: verified          # verified | needs-tool | blocked | unverified
requires: [open_app(a11y), see(tree), click(legacy)]
reviewed: true            # 用户是否审核过
date: 2026-11-07
---

## 目标
读取当前群聊的会话列表与未读状态

## 步骤
1. open_app(QQ.exe, accessibility=true)  ← 必须有三个 flag
2. windows() 找 hwnd
3. see(hwnd, with_tree=true) 读树，约 1.5 s

## 已知陷阱
- 失焦后树归零：必须带
  --disable-backgrounding-occluded-windows
  --disable-features=CalculateNativeWinOcclusion
- 点击用 Legacy 路由，InvokePattern 会抢前台
- 登录窗口不带 a11y，登录后才生效

## 未解决
滚动采集：滚轮 0 像素变化，ScrollPattern 报
VerticallyScrollable=False。1980 人群成员无法拉全。
```

### 3.2 三态 + 审核标签

`status` 表示**技术状态**：

| status | 含义 |
|---|---|
| `verified` | 实测通过 |
| `needs-tool` | 方案已探明，但现有 mcp 缺少某个工具 → 登记缺口 |
| `blocked` | 技术可行但被封（如 QQ CDP 端口）→ 不重试 |
| `unverified` | 探明但未充分验证 |

`reviewed` 表示**人是否确认过**。这两个维度独立：

- `verified: true` + `reviewed: false` —— agent 刚跑通，人还没看
- 召回时两条都返回，但未审核的带警示

这样积累不会被审批卡住，但 agent 知道哪些可以信任。

### 3.3 缺口登记

当方案状态是 `needs-tool` 时，同时在 `gaps.json` 留一条：

```json
{
  "id": "scroll-virtualized",
  "app": "QQ@9.9.22",
  "need": "在后台滚动虚拟化列表，不移动光标",
  "tried": ["mousewheel(0 px)", "ScrollPattern(COMError, VerticallyScrollable=False)"],
  "impact": "无法批量拉取 >渲染范围 的群成员/聊天记录",
  "date": "2026-11-07"
}
```

这是 mcp 演进的待办来源——不是靠人想该加什么，是实际问题在推。

### 3.4 索引：精确版本，方案可被多条索引共享

```
index.json
{
  "QQ@9.9.22":   { "playbook": "qq-app.md",   "fixtures": ["qq@9.9.22"] },
  "QQ@9.9.19":   { "playbook": "qq-app.md",   "fixtures": ["qq@9.9.19"] },
  "Code@1.96":   { "playbook": "vscode.md",   "fixtures": [] }
}
```

同一方案可被多条索引指向。某个版本行为变了，只拆那一条，其他不受影响。

索引本身很小（几百字节），可以整个注入上下文；方案正文按需取。

### 3.5 专用工具：可插拔、按需加载

当现有原语组合不出某个能力时，为那个软件写一个专用工具，放在：

```
%LOCALAPPDATA%\winmcp\plugins\
  qq_roster.py        # 声明 TOOL_META + def run(...)
  __manifest__.json   # 工具名 → 文件 → 依赖
```

MCP 启动时只读 manifest，**不导入代码**。agent 主动调用时才加载执行。

这样：
- 主库保持干净
- 一个软件的专用工具坏了不影响别的
- 用户可以自己丢一个 .py 进去

## 4. MCP 新增的接口

现有 8 个工具保留。新增 4 个：

| 工具 | 作用 |
|---|---|
| `recall(query, version=None)` | 按索引取方案。返回方案正文 + status + reviewed + 缺口 |
| `remember(...)` | 写一条方案。默认 `reviewed: false`，需用户确认才置 true |
| `gaps()` | 列出所有未填的能力缺口 |
| `plugins()` | 列出可用专用工具及其加载状态 |

`recall` 的返回必须包含 status 和 reviewed——agent 要知道这条方案可不可信。

## 5. skill 层

新增一个 skill：`windows-app-automation`。内容不是工具说明（那是 MCP 的职责），而是**探索方法**：

1. 先 `recall("app@version")`，有方案就照做
2. 没有方案，按固定顺序探测：窗口枚举 → 读树 → 判空壳 → Electron 就试 a11y flag → …
3. 记录每一步的结果，包括失败的
4. 探明后 `remember(...)` 询问用户
5. 现有工具做不到的，写进 `gaps()`

关键：skill 里要**明确写出"还没试过的方向"**，比如：

> 若滚轮和 ScrollPattern 都失败，未试的方向：`--disable-features` 的其他组合
> （如同时关 GPU 合成）、`--disable-gpu`、强制 software rendering。
> 这些可能让滚轮生效，但会显著降低应用性能，需用户同意。

这句话本身是新知识——它把"我知道还有路没走"传下去。

## 6. 不做的事

- **不改 ScreenHand 的代码来适配**：它是 TypeScript + .NET，我们是 Python，硬接成本高于收益。借它的设计，不借代码。
- **不做全自动记忆**：ScreenHand 每次调用都记，会把"重启后失效"这种假结论存进去。我们只在探明后、经用户确认才写。
- **不做跨机器同步**：memory 是本机事实（软件版本、路径、用户设置），跨机器同步会带来错误的确定性。
- **不追求工具数量**：原语正交比数量重要。宁可 8 个能组合出 80 种，不要 80 个各管一件事。

## 7. 验收标准

1. 给定一个全新软件（如记事本之外任意程序），agent 能按 skill 走完探测流程并写出方案
2. `recall` 能按「软件@版本」取回方案，索引共享生效（两条索引指向同一方案）
3. 未审核方案召回时带警示，agent 会选择先验证
4. 缺口能登记、能查询
5. 专用工具能放进 plugins/ 并按需加载，主库不受影响
6. 现有 36 项自检全部通过（不能因为加框架而破坏已有能力）

## 8. 风险

| 风险 | 缓解 |
|---|---|
| 框架比工具本身重，agent 反而不愿用 | skill 只写"怎么想"，不写"怎么调"；MCP 工具描述保持自解释 |
| 未审核方案污染判断 | 召回必带 reviewed 标记，skill 要求未审核的先验证 |
| 专用工具失控（无限增长、互相冲突） | manifest 显式登记，加载时报告依赖，不自动执行 |
| 版本索引膨胀 | 索引项极小，可整体注入；方案正文按需读 |
