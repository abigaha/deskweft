# winmcp 三层框架 — 实施交接文档

日期：2026-11-08
状态：设计已批准，待实现
前置阅读：`docs/specs/2026-11-08-three-layer-design-v2.md`（设计与理由）
本文件：**只讲怎么实现**。读完这份就能直接写代码，不需要回顾任何对话。

---

## 0. 一句话说清要做什么

给现有的 winmcp（8 个工具）加 5 个工具和 1 个 skill：

- **3 个能力逃生口**：`app_info` / `invoke_pattern` / `post_message`
- **2 个记忆工具**：`recall` / `remember`（外加 `approve` / `confirm_proven` 两个审核动作）
- **1 个 skill**：`windows-app-automation`，教 agent 遇到陌生软件怎么探测

不引入插件系统、不引入数据库、不改现有 8 个工具的行为。

---

## 1. 当前代码状态（实现前必须知道）

### 1.1 仓库位置与结构

```
C:\Users\32677\source\winmcp\        ← git 仓库，master，HEAD = cf5c2ea
  winmcp\
    __init__.py      0 lines
    server.py      159 lines   MCP 工具定义 + INSTRUCTIONS + main()
    act.py         342 lines   动作层：click/type/key/scroll 的全部路由
    tree.py        134 lines   UIA 树读取、pattern 访问守卫
    launch.py      184 lines   启动程序、强制前台
    win32.py       227 lines   Win32 API 封装、窗口枚举、PrintWindow 截图
    check.py       211 lines   36 项自检
  docs\specs\        设计文档
  install.ps1 / uninstall.ps1 / run-helper.ps1 / start.cmd / README.md
```

运行时：`%LOCALAPPDATA%\winmcp\`（venv + 日志），**代码以 editable 方式指向上面这个仓库**。
改仓库代码后必须同步到运行时副本并重启服务，见 §8。

### 1.2 现有 8 个工具（server.py）

```python
open_app(command, args="", settle=2.5, show=False, accessibility=False) -> dict
reveal(hwnd) -> dict
windows() -> list[dict]
see(hwnd, with_tree=False, timeout_ms=1500, max_elements=200)
click(hwnd, target="", allow_foreground=False) -> dict
type_text(hwnd, target="", text="", allow_foreground=False) -> dict
key(hwnd, keys="", allow_foreground=False) -> dict
scroll(hwnd, target="", direction="down", allow_foreground=False) -> dict
```

### 1.3 可复用的内部函数（不要重写）

| 模块 | 函数 | 用途 |
|---|---|---|
| `win32` | `title(hwnd)` / `class_name(hwnd)` | 读窗口标题/类名 |
| `win32` | `foreground()` | 当前前台 hwnd |
| `win32` | `list_windows()` | 枚举可见顶层窗口，返回 dict 列表 |
| `win32` | `grab(hwnd)` | PrintWindow 截图，返回 `(png_bytes, w, h)` 或 None |
| `win32` | `children(hwnd)` | 枚举子窗口（原生控件） |
| `win32.user32` | ctypes WinDLL | 已声明好大量 argtypes，可直接用 |
| `tree` | `read(hwnd, timeout_ms, max_elements)` | 返回 `(elements, timed_out)` |
| `tree` | `find(elements, ref)` | 按名字/AutomationId 查找 |
| `tree` | `pattern(el, name)` | **取 UIA pattern 的唯一安全入口**，不要直接 `el.GetXxxPattern()` |
| `tree` | `_PATTERN_NAMES` | 当前 7 个已知 pattern 名 |
| `launch` | `force_foreground(hwnd)` | 抢前台（带 AttachThreadInput），返回是否成功 |
| `launch` | `is_shown(hwnd)` | 可见且非最小化 |
| `act` | `act(hwnd, action, target, text, allow_foreground)` | 统一动作入口，含 Legacy 优先路由 |
| `act` | `_done(...)` | 统一成功返回结构 |

### 1.4 项目约定（新代码必须遵守）

**返回结构**（成功）：

```python
{"ok": True, "action": ..., "route": ..., "took_ms": ...,
 "foreground_changed": bool, "foreground_before": hwnd, "foreground_after": hwnd,
 "window": title}
```

**返回结构**（失败）：

```python
{"ok": False, "reason": "短句", "detail": "具体说明", "hint"?: "下一步该做什么"}
```

需要用户授权的失败额外带 `"needs_permission": True`。

**代码风格**：注释只写"为什么"，一行；不写"做了什么"。所有 pattern 访问走 `tree.pattern()`。

---

## 2. 新模块：memory.py

### 2.1 文件位置

新建 `winmcp/memory.py`，约 200-260 行。

存储根目录：

```python
MEMORY_ROOT = Path(os.environ.get("WINMCP_MEMORY_DIR")
                   or Path(os.environ["LOCALAPPDATA"]) / "winmcp" / "memory")
PLAYBOOKS = MEMORY_ROOT / "playbooks"
PLANS = MEMORY_ROOT / "plans"
```

注意：**不在 git 仓库内**。这是本机事实，不进版本控制。

### 2.2 目录结构

```
%LOCALAPPDATA%\winmcp\memory\
  playbooks\
    QQ@9.9.22.md          ← 一个 key 一个文件
    Code@1.96.md
  plans\
    QQ@9.9.22--A.md       ← 方案正文，key--id.md
    QQ@9.9.22--B.md
```

文件名校验（防路径穿越）：key 和 id 只允许 `[A-Za-z0-9._@-]`，其余字符替换为 `_`。**必须在拼路径前校验**。

### 2.3 playbook 文件格式

`playbooks/QQ@9.9.22.md`：

```markdown
---
key: QQ@9.9.22
app: QQ
version: 9.9.22
updated: 2026-11-08
verified_with: winmcp 0.1.0
plans:
  - id: B
    summary: 不抢前台，读树约 1.5s
    cost: 比强前台慢约 30 倍
    uses_foreground: false
    reviewed: true
    proven: true
    body: plans/QQ@9.9.22--B.md
  - id: A
    summary: 强前台，约 50ms，最快
    cost: 抢走光标并改变前台，会打断你
    uses_foreground: true
    reviewed: true
    proven: false
    body: plans/QQ@9.9.22--A.md
---

## 未解决
滚动采集：滚轮 0 像素变化，ScrollPattern 报
VerticallyScrollable=False。1980 人群成员无法拉全。
```

**字段说明：**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `key` | str | 是 | `app@version`，必须与文件名一致 |
| `app` | str | 是 | 软件名 |
| `version` | str | 是 | 版本号 |
| `updated` | str | 是 | `YYYY-MM-DD` |
| `verified_with` | str | 否 | 验证时的 winmcp 版本 |
| `plans` | list | 是 | 至少 1 条 |
| `plans[].id` | str | 是 | 短标识，如 `A` `B` |
| `plans[].summary` | str | 是 | 一句话说清是什么 |
| `plans[].cost` | str | 是 | 代价，给人看 |
| `plans[].uses_foreground` | bool | 是 | 是否抢前台 |
| `plans[].reviewed` | bool | 是 | 人是否认可 |
| `plans[].proven` | bool | 是 | 是否多次实战通过 |
| `plans[].body` | str | 是 | 相对 `memory/` 的路径 |

**继承写法**（版本间共享）：

```markdown
---
key: QQ@9.9.19
app: QQ
version: 9.9.19
see: QQ@9.9.22
updated: 2026-11-08
---
```

有 `see:` 时忽略 `plans`，recall 时跟随一次并标注 `inherits: "QQ@9.9.22"`。

### 2.4 frontmatter 解析

**不要引入 PyYAML 依赖做这件事**——运行时 venv 里有 yaml（windows-mcp 带的），但为了减少耦合，建议手写最小解析器：

- 只支持 `key: value`、`  - id: x`、`    field: value` 这种两级嵌套
- 值的类型推断：`true`/`false` → bool，纯数字 → int，其余 → str
- 遇到无法解析的行 → 跳过并记入返回的 `warnings`

或者直接用 `yaml.safe_load()`，运行时已有。**二选一，实现时验一下 `yaml` 可导入即可**。

### 2.5 核心函数

```python
def rank(reviewed: bool, proven: bool) -> int:
    """11 > 01 > 10 > 00 => proven*2 + reviewed"""
    return (2 if proven else 0) + (1 if reviewed else 0)


def recall(query: str, max_body_chars: int = 6000) -> dict:
    """按 query 取方案。永不返回全表。"""

def remember(app, version, plan: dict, overwrite=False, append=True) -> dict:
    """写方案。默认 reviewed=False, proven=False。"""

def approve(app, version, plan_id, reviewed=True) -> dict:
    """置 reviewed 位。"""

def confirm_proven(app, version, plan_id, proven=True) -> dict:
    """置 proven 位。"""

def list_keys() -> list[str]:
    """列出所有 key（不含正文，约 20 tokens/条）。"""

def unresolved() -> list[dict]:
    """派生缺口：扫描所有 playbook 的 '## 未解决' 段落。"""
```

### 2.6 recall 的匹配规则（必须严格按此实现）

```
输入 query：
  1. 含 "@"        → 精确匹配 key
                     未命中 → 取 app 部分，返回该 app 所有版本，exact=false
  2. 含 ".exe" 或 "\" 或 "/"  → 取文件名部分作为 app，同 3
  3. 其他          → app 名不区分大小写的子串匹配
                      多个 app 命中 → 全部返回
  4. 空字符串      → 返回 list_keys() 的结果，不含正文
```

**返回**：

```python
{
  "matches": [
    {
      "key": "QQ@9.9.22",
      "plans": [
        {"id": "B", "summary": "...", "cost": "...",
         "uses_foreground": False, "reviewed": True, "proven": True,
         "rank": 3, "body": "## 步骤\n..."},
        ...
      ],
      "unresolved": "滚动采集：滚轮 0 像素变化…",
      "inherits": None,
      "truncated": False,
    }
  ],
  "exact": True,
}
```

**规则**：

- `plans` 按 `rank` 降序排列
- 单条 `body` 超过 `max_body_chars` 时截断，`truncated: True`
- 未命中：`{"matches": [], "exact": False}`，**这是成功不是错误**
- 有 `see:` 时：跟随一次，`inherits` 填被继承的 key，`plans` 用被继承者的

### 2.7 remember 的写入规则

```
输入：app, version, plan{id, summary, cost, uses_foreground, body}
1. key = f"{app}@{version}"
2. 校验文件名安全
3. playbook 路径 = PLAYBOOKS / f"{safe(key)}.md"
4. 若已存在：
   - 同 plan.id 已存在 且 not overwrite → 返回 {"ok": False, "reason": "plan exists", ...}
   - append=True 且新 id → 追加到 plans
   - overwrite=True → 替换该 plan
5. 若不存在：创建 playbook，plans=[该plan]
6. body 写到 PLANS / f"{safe(key)}--{safe(id)}.md"
7. 原子写：写 .tmp 再 os.replace()
8. 返回 {"ok": True, "path": "...", "plan_id": "...", "rank": 0}
```

**并发**：服务是 `stateless_http=True`，两个会话可能同时 remember。用文件锁（`portalocker` 不在依赖里，用 `os.open(lock, O_CREAT|O_EXCL)` 轮询，或简单点：先写临时文件，`os.replace` 本身是原子的，够了）。

### 2.8 unresolved 的派生

扫描所有 playbook，提取 `## 未解决` 到下一个 `## ` 或文件末尾的内容：

```python
def unresolved() -> list[dict]:
    out = []
    for f in PLAYBOOKS.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^## 未解决\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        if m and m.group(1).strip():
            out.append({"key": ..., "text": m.group(1).strip()})
    return out
```

没有独立文件、没有 id、没有关闭状态——段落删掉缺口就消失。

---

## 3. 新工具：app_info

### 3.1 放在哪

`winmcp/appinfo.py`，约 80 行。或直接写进 `win32.py`（如果不想多一个文件）。

### 3.2 版本来源（**这里踩过坑，必须按此实现**）

实测 QQ 两个来源不一致：

| 来源 | 值 |
|---|---|
| `FileVersionInfo.FileVersion` | `9.9.19.35469` |
| `<install>\versions\` 目录名 | `9.9.22-40824` |

**取前两段会得到 `9.9`，完全错误。**

实现顺序：

```python
def app_info(hwnd: int) -> dict:
    pid = get_window_pid(hwnd)
    exe = get_process_path(pid)           # Win32Process / psutil
    install = os.path.dirname(exe)

    version = None
    source = None

    # 1. 优先 versions 目录
    vdir = os.path.join(install, "versions")
    if os.path.isdir(vdir):
        cands = [d for d in os.listdir(vdir)
                 if re.fullmatch(r"\d+(\.\d+)+(-\d+)?", d)]
        if cands:
            version = sorted(cands)[-1].split("-")[0]   # 9.9.22
            source = "program_dir"

    # 2. 回退 FileVersion
    if version is None:
        fv = file_version_info(exe)       # 9.9.19.35469
        if fv:
            version = ".".join(fv.split(".")[:2])  # 9.9
            source = "file_version"

    return {
        "ok": True,
        "name": Path(exe).stem,           # QQ
        "version": version,
        "source": source,
        "exe": exe,
        "file_version": fv,
        "product": info.get("ProductName"),
        "company": info.get("CompanyName"),
    }
```

**关键细节**：

- `versions\` 目录里有 `channel.json` / `config.json` / `setting.json` 等非版本文件，**必须用正则 `\d+(\.\d+)+(-\d+)?` 过滤**。实测没过滤时会取到 `setting.json`。
- FileVersion 回退时返回 `source: "file_version"`，让调用方知道可信度低。
- 取进程路径用 `psutil.Process(pid).exe()`（venv 里有 psutil）或 `Win32Process` ctypes。

### 3.3 签名

```python
@mcp.tool
def app_info(hwnd: int) -> dict:
    """Identify a window's program and version.

    Needed before recall(): the memory key is app@version, and nothing else
    returns a version. Prefers the program's versions/ directory, because
    FileVersion and the installed directory can disagree - QQ reports
    9.9.19.35469 while its program directory is 9.9.22-40824.
    """
```

---

## 4. 新工具：invoke_pattern

### 4.1 为什么需要

`act.py` 只硬编码了 6 个 pattern。实测 `Control` 上有更多（`GetPattern` 可拿任意一个）。skill 探出新 pattern（如 `SelectionPattern2`、`TextPattern`）时必须能发出去。

### 4.2 实现

放在 `act.py` 里，加一个 action：

```python
def act(hwnd, action, target="", text="", allow_foreground=False, pattern="", **kw):
    ...
    if action == "pattern":
        elements, _ = tree.read(hwnd, timeout_ms=3000, max_elements=600)
        hit = tree.find(elements, target)
        if hit is None:
            return {"ok": False, "reason": "no such control",
                    "detail": f"nothing named {target!r}"}
        pat = tree.pattern(hit["_el"], pattern)
        if pat is None:
            return {"ok": False, "reason": "pattern not supported",
                    "detail": f"{target!r} does not expose {pattern}"}
        # 调用该 pattern 上名为 text 的方法，或默认方法
        method = getattr(pat, text or default_method(pattern), None)
        if method is None:
            return {"ok": False, "reason": "no such method",
                    "detail": f"{pattern} has no {text}"}
        method()
        return _done(hwnd, action, target, f"uia:{pattern}",
                     fg_before, start)
```

`default_method(pattern)` 映射：

| pattern | 默认方法 |
|---|---|
| `InvokePattern` | `Invoke` |
| `TogglePattern` | `Toggle` |
| `SelectionItemPattern` | `Select` |
| `ExpandCollapsePattern` | `Expand` |
| `ScrollPattern` | `Scroll`（需参数，见下） |
| `ValuePattern` | `SetValue`（需参数） |
| 其他 | `DoDefaultAction` |

**带参数的 pattern**：`ValuePattern.SetValue(str)`、`ScrollPattern.Scroll(h, v)`、`RangeValuePattern.SetValue(float)`。

加一个 `args` 参数（JSON 字符串或 list），按位置传入：

```python
def invoke_pattern(hwnd, pattern, target="", method="", args=None):
    # args: list，传给 method
```

### 4.3 工具签名

```python
@mcp.tool
def invoke_pattern(hwnd: int, pattern: str, target: str = "",
                   method: str = "", args: list | None = None) -> dict:
    """Call any UI Automation pattern on a control.

    act.py's click/type/scroll cover the common patterns; this is the escape
    hatch for the rest (SelectionPattern2, TextPattern, TransformPattern...).
    Prefer it over driving the mouse: a pattern call does not move the cursor,
    and the legacy route does not take the foreground.
    """
```

### 4.4 安全

- 结果必须带 `foreground_changed`
- 不设白名单（pattern 调用本身不改变全局状态，最坏是改了这个控件的值）

**关于 pattern 名校验（这里有个坑，已实测）：**

`Control` 基类上只有 3 个 getter：

```
GetCachedPattern, GetLegacyIAccessiblePattern, GetPattern
```

那 7 个具名 getter（`GetInvokePattern` 等）**挂在具体控件子类上**（`ButtonControl` 有 `GetInvokePattern`，`GroupControl` 没有）。`tree.pattern()` 正是靠 `getattr(el, "Get" + name, None)` 动态取，取不到返回 None。

所以**不要**尝试用「Get*Pattern 列表白名单」校验 pattern 名——那个列表在基类上是残缺的。

正确做法：

```python
pat = tree.pattern(el, pattern)
if pat is None:
    return {"ok": False, "reason": "pattern not available on this control",
            "detail": f"{target!r} does not expose {pattern}",
            "hint": "read the tree first (see with_tree=true) to see which "
                    "patterns it lists"}
```

`see(with_tree=true)` 返回的每个 element 已经带 `patterns` 字段，列出了该控件支持的 pattern。让 agent 先看再调，比在服务端列一个可能不准的白名单可靠。

---

## 5. 新工具：post_message

### 5.1 实现

```python
@mcp.tool
def post_message(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0,
                 allow_unsafe: bool = False) -> dict:
    """Send a raw Win32 message to a window.

    Exploration tool, not a daily one. Only messages in a small safe set are
    accepted by default; anything else (WM_CLOSE, WM_DESTROY...) needs
    allow_unsafe=True. Always reports whether the foreground changed.
    """
```

### 5.2 白名单

```python
SAFE = {
    0x000C,  # WM_SETTEXT
    0x00F5,  # BM_CLICK
    0x000D,  # WM_GETTEXT
    0x000E,  # WM_GETTEXTLENGTH
    0x0201,  # WM_LBUTTONDOWN
    0x0202,  # WM_LBUTTONUP
    0x020A,  # WM_MOUSEWHEEL
    0x0102,  # WM_CHAR
    0x0100,  # WM_KEYDOWN
    0x0101,  # WM_KEYUP
    0x000F,  # WM_PAINT
    0x0233,  # WM_POWERBROADCAST (harmless)
}
```

非白名单且 `not allow_unsafe` → 返回 `{"ok": False, "reason": "message not in safe set", "detail": f"0x{msg:04X} 需要 allow_unsafe=True", "hint": "确认这条消息不会关闭或破坏窗口后再试"}`

### 5.3 发送方式

**这两个函数已经声明好了，直接用**（`win32.py` L28-31）：

```python
win32.user32.SendMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
win32.user32.SendMessageW.restype  = LPARAM     # 能拿到返回值
win32.user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
win32.user32.PostMessageW.restype  = BOOL
```

优先 `SendMessageW`（同步，能拿到返回值），加 `wait: bool = True` 参数切换。

返回值里带上 `result`（SendMessageW 的返回，对 WM_GETTEXT 等有意义）。

---

## 6. 新工具：recall / remember / approve / confirm_proven

直接包 `memory.py`：

```python
@mcp.tool
def recall(query: str) -> dict:
    """Look up known plans for an app.

    Pass "app@version" for an exact hit, or just an app name to see every
    version. Never returns the whole catalogue - query a name you care about.

    Plans come back sorted by rank: proven-and-reviewed (3) first, then
    proven-only (2), reviewed-only (1), then new (0). A rank-0 plan has not
    been validated; follow the exploration steps before trusting it.
    Every plan carries uses_foreground - never use a foreground plan while
    the user is working.
    """
    return memory.recall(query)


@mcp.tool
def remember(app: str, version: str, plan_id: str, summary: str,
             cost: str, body: str, uses_foreground: bool = False,
             append: bool = True, overwrite: bool = False) -> dict:
    """Record a plan you just worked out.

    Written as rank 0 (neither reviewed nor proven). Tell the user it is
    unverified rather than presenting it as settled.
    """
    ...


@mcp.tool
def approve(app: str, version: str, plan_id: str) -> dict:
    """Mark a plan as reviewed by the user. Ask them first."""


@mcp.tool
def confirm_proven(app: str, version: str, plan_id: str) -> dict:
    """Mark a plan as validated by repeated real use. Ask them first."""
```

---

## 7. 新 skill：windows-app-automation

### 7.1 放哪（三个客户端的机制不同，已实测）

| 客户端 | 路径 | 当前形态 |
|---|---|---|
| DSH | `~/.dsh/skills/windows-app-automation/` | **实体目录** |
| Codex | `~/.codex/skills/windows-app-automation` | **Junction**（`relay-imagegen` 就是这样，指向 `C:\Users\32677\source\relay-imagegen`） |
| Claude | `~/.claude/skills/windows-app-automation/` | **实体目录**（复制） |

推荐做法：

1. 把 skill 源码放在 `C:\Users\32677\source\winmcp\skills\windows-app-automation\SKILL.md`
2. DSH 和 Claude 用复制（或也建 junction）
3. Codex 建 junction：

```powershell
New-Item -ItemType Junction `
  -Path "$env:USERPROFILE\.codex\skills\windows-app-automation" `
  -Target "C:\Users\32677\source\winmcp\skills\windows-app-automation"
```

**注意**：Codex 的 junction 指向的是**源码目录**（`source\relay-imagegen`），不是运行时目录。照此办理。

改完 skill 后要重启客户端才生效。

### 7.2 frontmatter

```yaml
---
name: windows-app-automation
description: Use when automating an unfamiliar Windows application through winmcp, or when a window reads as empty/unnamed elements, or a click does not land. Explains how to probe a new app, which routes keep the foreground, and what to record. 关键词：控制陌生软件、读不到界面、window reads empty、click 不生效
---
```

### 7.3 正文（照抄，这是整层的价值）

```markdown
# Windows 应用自动化

## 探测顺序（遇到陌生软件按此走，不要跳步）

1. `app_info(hwnd)` 拿 name + version
2. `recall("name@version")`
   - 命中 rank ≥ 2 → 照做，跳过探测
   - 命中 rank 1 → 照做但每步验证
   - 命中 rank 0 或未命中 → 继续
3. `see(hwnd, with_tree=true)`
   - 树非空且有名字 → 走 UIA 路线
   - 只有空 PaneControl → 记录"疑似 Chromium/Electron"，转 4
4. 疑似 Electron：用 `open_app(exe, accessibility=true)` 重新启动
   - 树变丰富（QQ 从 9 → 132 个元素）→ 成功，记住
   - 仍为空 → 记录"a11y 无效"，转 5
5. 视觉兜底 `see(hwnd)` 截图
   - **注意**：虚拟化列表（长名单、历史消息）在屏幕外不存在，
     视觉只能看到碰巧渲染的那几行。不要以为"看清了"。
6. 全部失败 → `remember(...)`，body 的「未解决」写明试过什么

## 点击路由（winmcp 已自动选择，但你要理解）

`click` 的优先级：窗口消息 → LegacyIAccessible.DoDefaultAction → InvokePattern → 光标。

实测差异（QQ）：

| 路由 | 生效 | 动光标 | 抢前台 |
|---|---|---|---|
| Legacy DoDefaultAction | 是 | 否 | **否** |
| InvokePattern | 否 | 否 | **是** |

所以看到 `route: uia:legacy-default` 是好事，说明没打扰用户。

## 选方案（同 key 有多个 plan 时）

1. rank = proven*2 + reviewed，降序
2. **用户正在用电脑** → 立刻排除 `uses_foreground: true` 的全部方案，
   哪怕它 rank 最高。抢前台是唯一红线。
3. 剩下按 cost 权衡：要快要准还是要不打扰
4. 选中的是 rank 0 → **先按探测顺序验证一遍**，通过再照做
5. 用户离开时可用强前台方案，但先说"这会占用屏幕"

## 写记忆

探明后 `remember(...)`，新方案记为 rank 0。
告诉用户"已记录，未审核、未实战验证"。
用户认可后用 `approve`，多次跑通后用 `confirm_proven`。

## 已知的未试方向（探到时优先试）

- 滚轮无效时可试 `--disable-gpu` 强制软件渲染（明显降性能，需用户同意）
- `--disable-features` 的其他组合（含关 GPU 合成）
- 后台读树失败时，试不带 `--force-renderer-accessibility` 的裸启动做对照

这些试完，把结果写进方案的「未解决」或新方案里。
```

---

## 8. 开发与部署流程

### 8.1 改代码后必须同步

代码在 `C:\Users\32677\source\winmcp`（仓库），运行时在 `%LOCALAPPDATA%\winmcp`（venv + 日志）。
venv 已用 editable 指向仓库，**但 `.py` 改动需要重启服务才生效**。

```powershell
# 1. 跑自检
cd C:\Users\32677\source\winmcp
$env:PYTHONUTF8=1
& "$env:LOCALAPPDATA\winmcp\.venv\Scripts\python.exe" -m winmcp.check

# 2. 同步到运行时副本（虽然 editable，但为了保险）
Copy-Item "C:\Users\32677\source\winmcp\winmcp\*.py" "$env:LOCALAPPDATA\winmcp\winmcp\" -Force

# 3. 重启服务
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*winmcp.server*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName "winmcp-helper"
Start-Sleep -Seconds 14
"port: " + (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count
```

### 8.2 注意：Start-ScheduledTask 偶尔报工具错误

`Start-ScheduledTask` 有时会让 pwsh 工具返回 `Windows Job runner exited with exit code 4294967295`。
**这是工具层的报错，任务通常已经启动了。** 重跑一次确认端口即可，不要重复重启。

### 8.3 push 会遇到凭据弹窗（已验证 3 次）

`git push` 会卡住，因为 Windows 凭据管理器弹出 `Select an account`（Avalonia 窗口，标题不含 "git"，关键字扫描找不到）。

处理：

```powershell
# 1. push 放后台
$job = Start-Job { Set-Location C:\Users\32677\source\winmcp; git push origin master 2>&1 }

# 2. 等 25 秒后找弹窗
& "$env:LOCALAPPDATA\winmcp\.venv\Scripts\python.exe" -c @"
import sys; sys.path.insert(0, r'$env:LOCALAPPDATA\winmcp')
from winmcp import win32
for w in win32.list_windows():
    if 'Avalonia' in w['class'] or 'Select an account' in w['title']:
        print('DIALOG:', w['hwnd'])
"@

# 3. 点掉：先在第一个 ListItem 上点一下，再点 Continue
#    坐标约 (960, 525) 和 Continue 按钮，或用 act.act(h,'click',target='Continue')
```

**代理**：全局 git 代理是 `127.0.0.1:7890`（7897 是死的）。

---

## 9. 验收清单（逐条可判）

实现完成后必须全部通过：

| # | 检查项 | 怎么判 |
|---|---|---|
| 1 | `app_info` 返回 QQ 版本 `9.9.22` | 对运行中的 QQ 调用，`source == "program_dir"` |
| 2 | `app_info` 的 versions 目录过滤正确 | 断言没取到 `setting.json` |
| 3 | `invoke_pattern` 能调 act.py 没硬编码的 pattern | 用 `ExpandCollapsePattern` 在真实控件上验证 |
| 4 | `post_message` 白名单外被拒 | 传 `WM_CLOSE`，确认需要 `allow_unsafe` |
| 5 | `recall` 精确命中 | `recall("QQ@9.9.22")` → `exact: true` |
| 6 | `recall` 家族回退 | `recall("QQ@9.9.99")` → `exact: false`，返回同 app 其他版本 |
| 7 | `recall` 未命中是成功 | `recall("不存在")` → `ok: true, matches: []` |
| 8 | plans 按 rank 降序 | 造两条（3 和 1），断言顺序 |
| 9 | `remember` 原子写 | 检查无 `.tmp` 残留 |
| 10 | `remember` 默认 rank 0 | `reviewed: false, proven: false` |
| 11 | `remember` 冲突检测 | 同 id 再写 → 报冲突；`overwrite=True` 成功 |
| 12 | `approve` / `confirm_proven` 独立生效 | 分别置位，rank 相应变化 |
| 13 | 继承（`see:`）工作 | 造两个文件，`inherits` 字段正确 |
| 14 | `unresolved` 派生正确 | 段落删掉后缺口消失 |
| 15 | **现有 36 项自检全过** | `python -m winmcp.check` |
| 16 | **新增断言并入 check.py** | 断言总数 > 36 |

---

## 10. 实现顺序建议

1. **`memory.py`** + 自检（最容易独立验证，不依赖窗口）
2. **`app_info`** + 自检（对着真实 QQ 跑）
3. **`recall` / `remember` / `approve` / `confirm_proven`** 四个工具包装
4. **`invoke_pattern`**（改 act.py，注意别破坏现有路由）
5. **`post_message`**（最独立）
6. **skill 文件**
7. 更新 README 和 `INSTRUCTIONS`
8. 全量回归 + push

**每完成一项就跑一次 `python -m winmcp.check`**，不要攒到最后。

---

## 11. 已知陷阱（都是这两天踩过的）

| 陷阱 | 表现 | 后果 |
|---|---|---|
| 版本取前两段 | `9.9.19.35469` → `9.9` | key 全错 |
| versions 目录不过滤 | 取到 `setting.json` | key 变成 `setting.json` |
| Chromium 失焦丢树 | 窗口切走 → 0 元素 | 误判为"重启失效" |
| 修复：两个 flag | `--disable-backgrounding-occluded-windows` + `--disable-features=CalculateNativeWinOcclusion` | 已进 `launch()` |
| InvokePattern 抢前台 | `foreground_changed: true` | 打断用户 |
| 修复：Legacy 优先 | `act()` 已改，先试 legacy | 已验证 |
| `el.GetXxxPattern()` 裸调用 | `AttributeError` | 崩溃（已修 3 次） |
| 一律走 `tree.pattern(el, name)` | — | — |
| skill 提到方案但 MCP 做不到 | — | 新增 `invoke_pattern` / `post_message` 解决 |

---

## 12. 参考数据（实测，可用于断言）

**QQ 9.9.22 a11y 对比：**

| 状态 | 元素数 | 有名字 |
|---|---|---|
| 无 flag | 9 | 0 |
| 有 a11y flag，前台 | 132 | 130 |
| 有 a11y flag，后台（有防降级 flag） | 132 | 130 |
| 有 a11y flag，后台（无防降级 flag） | 0 | 0 |

**读树耗时**：QQ 主窗口约 1.5s / 135 元素；Edge 约 1.4s / 251 元素。

**点击路由实测：**

| 路由 | 生效 | 动光标 | 抢前台 | 耗时 |
|---|---|---|---|---|
| `LegacyIAccessible.DoDefaultAction` | 是 | 否 | 否 | ~500ms |
| `InvokePattern.Invoke` | 否 | 否 | 是 | ~510ms |
| `PostMessage(WM_LBUTTONDOWN)` 到渲染宿主 | 否 | 否 | 否 | 0ms |
| 真实光标点击 | 是 | 是 | 是 | ~3.5ms |

**滚轮在 QQ 无效**：0 像素变化（同样代码在记事本 7367 像素）。
`ScrollPattern` 报 `COMError`，`VerticallyScrollable=False`。

---

## 13. 未决问题（留给实现者判断）

1. **frontmatter 用手写解析还是 `yaml.safe_load`**：运行时 venv 有 yaml，但引入依赖会增加耦合。建议先试 `yaml`，验证可导入即可。
2. **`proven` 的自动置位**：设计里说 MVP 手工填。如果实现时发现"多次成功"容易统计，可以加，但**不能自动**——要用户确认。
3. **skill 传播到 Codex/Claude**：检查 `~/.codex/skills/relay-imagegen` 是否是 junction，照做。如果不是，可能要用别的机制，实现时确认。
4. **`recall("")` 返回 key 列表**：设计里说约 20 tokens/条。如果条目很多（>100），可能要分页，但 MVP 先不做。
