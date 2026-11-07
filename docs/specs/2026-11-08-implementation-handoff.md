# winmcp 三层框架：实施交接

审核修订：2026-11-08。文件日期不表示功能已经完成。
状态：审核修订稿，尚未实现；原两文档审批状态不一致，本次不推断审批结果。
设计理由见 [three-layer-design-v2](2026-11-08-three-layer-design-v2.md)。**本文件是签名、字段、行为和验收的唯一契约。**

## 0. 实施者必须先读的目标

本框架有三个并列目标：**skill 提供足够广的探索思路，memory 清楚保存经验与不确定性，MCP 为这些思路提供可靠的执行与读回能力。** 优化围绕这三个目标展开，不能用删掉探索方向、忽略返回值或统一拒绝复杂操作来代替可靠实现。原定 7 个新增工具均在本轮范围内，不采纳“先删去通用出口和审核工具”的缩减建议。

交接对象可能不具备设计者的推理能力。实现时必须逐项落实本文的路径、签名、字段、分支、错误及测试，不依赖历史对话；不能把“接口已注册”“API 没抛错”“消息已入队”当成任务成功。下文代码块中用 `...` 表示签名的部分不是实现，具体算法由其后的规则限定；缺少平台能力时必须报告具体缺口，不能编造成功。

历史实测与未试方向的完整资料在设计稿 §7，各项数字保留原口径并注明缺失的环境证据。它们是实施与复测输入，不能在再次精简时删除。

## 1. 范围与基线

基线提交：`abb55bd`；实施前重新检查 `git status` 和实际导入路径，不依赖固定行号或机器上的旧副本。

- 保留现有 8 个 MCP 工具的签名：`open_app`、`reveal`、`windows`、`see`、`click`、`type_text`、`key`、`scroll`。
- 新增 **7 个** MCP 工具：`app_info`、`invoke_pattern`、`post_message`、`recall`、`remember`、`approve`、`confirm_proven`；合计 15 个。
- 新增 `skills/windows-app-automation/SKILL.md`。不做插件、数据库、自动计数、跨机同步或记忆浏览 UI。
- 本轮只支持一个服务进程写一个 memory 根目录；同进程的并发 MCP 会话必须安全。人工编辑前先停止服务。

### 1.1 修改落点

| 路径 | 修改内容与相关调用方 |
|---|---|
| `winmcp/memory.py`（新） | 单文件记录、匹配、排序、继承、写入和审核；由 server 包装调用 |
| `winmcp/appinfo.py`（新） | hwnd → pid → exe → 版本证据；复用 win32 的窗口元数据 |
| `winmcp/tree.py` | 扩展 `pattern` / `patterns`，增加 `pattern_detailed` / `read_detailed` 诊断入口和 `native_hwnd`；调用方为 `describe`、`act`、`check`；保留现有签名 |
| `winmcp/act.py` | 新增独立 `invoke_pattern`，复用 `_done`；增加有界结果投影；修正目标歧义和未命中时点窗口中心的分支，不把新参数塞进现有 `act()` |
| `winmcp/launch.py` | 两段隐藏/回交前台循环共用进程归属判断，只作用于已确认的启动目标；无法确认单实例/broker窗口时如实报告 |
| `winmcp/uia_worker.py`（新） | 单个可回收 UIA 子进程、串行调度、超时与初始化；不把 COM 对象交给 HTTP 线程 |
| `winmcp/win32.py` | 新增 `post_message`；同步用 SendMessageTimeoutW、异步用 PostMessageW，服务端托管受支持的文本缓冲区 |
| `winmcp/server.py` | 7 个工具包装；UIA 请求交给 worker；修正 INSTRUCTIONS 与真实路由不符的描述 |
| `pyproject.toml` | 显式增加 `PyYAML>=6,<7`；其余新增功能用标准库与已有 UIA 依赖 |
| `tests/test_memory.py`、`tests/test_tools.py`、`tests/test_uia_worker.py`（新） | 临时目录、假 provider 和假 worker 的行为测试，无需真实 QQ |
| `winmcp/check.py` | 先收紧清理范围，再增加自建测试窗口的集成验证 |
| `README.md`、`skills/windows-app-automation/SKILL.md` | 工具清单、权限和探索流程，与本契约一致 |

### 1.2 可复用入口及限制

`win32.title/class_name/foreground/list_windows/children`、`tree.read/find/pattern`、`launch.force_foreground/is_shown`、`act._done` 均已存在。

必须按实际代码理解这些入口：

- 当前 `act()` 在尝试 Legacy 路由**之前**检查 `allow_foreground`。默认 `click()` 只尝试原生控件消息，不能宣称默认执行后台 Legacy 点击。
- 当前 `tree.pattern()` 只找具名 getter；`patterns()` 只探测 7 项并返回小写，不是完整能力清单。
- `tree.read()` 过滤无名字、无已知 pattern 的容器及 offscreen 元素；空结果不能证明应用没有 UIA。
- 读树时间预算只在 Python 遍历间隙检查，不能中断一次阻塞的 provider/COM 调用。不要承诺硬超时。

### 1.3 共同返回约定

所有进入函数的新增工具调用成功包含 `ok: true`；业务失败包含 `ok: false, reason: str, detail: str`，可选 `hint`、`needs_permission`。`recall` 没找到是成功。尚未进入函数的 schema/协议错误由 FastMCP 返回标准参数错误，不伪造成 provider 故障；验收要证明工具函数未执行。

通过参数解析并进入窗口工具的请求，无论成功、拒绝还是抛错，都补上：

```python
{"foreground_before": before, "foreground_after": after,
 "foreground_changed": before != after}
```

`foreground_changed` 只是调用前后两个采样点的观测，不能证明中途没抢焦点，也不能替代事前授权。UIA 执行成功和消息入队均不等于业务目标已完成；调用方必须验证效果。

本文 int/bool/str 表示严格 JSON 类型，不接受 true 当1、字符串"true"当授权或数字转成字符串。FastMCP 的包装层使用已有 Pydantic 的 `StrictInt/StrictBool/StrictStr` 或等价 strict 注解，nullable version 用 `StrictStr | None`；参数名、默认值与 JSON 工具类型保持本文签名。[S15] 仅在函数内部做 isinstance 校验不足以防止框架先强制转换；HTTP/MCP 测试必须用真实 bool/字符串错类型确认拒绝。内部函数仍校验，不能只依赖包装层。

## 2. memory.py：唯一存储格式

### 2.1 根目录与文件名

```python
from hashlib import sha256
from pathlib import Path
import os

def memory_root() -> Path:
    configured = os.environ.get("WINMCP_MEMORY_DIR")
    return (Path(configured).expanduser() if configured else
            Path(os.environ["LOCALAPPDATA"]) / "winmcp" / "memory")

def make_key(app: str, version: str | None) -> str:
    tag = "unversioned" if version is None else version.strip()
    return app.strip().casefold() + "@" + tag

def record_path(root: Path, key: str) -> Path:
    return root / "playbooks" / (sha256(key.encode("utf-8")).hexdigest() + ".md")
```

每个 key 一个 `.md` 文件，文件名只由摘要生成；真实 key 留在 frontmatter。不要把中文或非法字符替换为 `_`，不同名称会发生碰撞。`plan_id` 不参与路径。

入口先验证 app 为非空字符串、无 `@`、无控制字符、无 `/` 或 `\`；app 使用 exe stem 而非路径。version 为符合相同字符约束的非空字符串，或明确的 None；字符串 `unversioned` 为保留值，调用方必须用 None 表示未知，不能伪造实际版本。`plan_id` 必须匹配 `[A-Za-z0-9_-]{1,32}`。读取时核对 `key == make_key(app, version)` 且路径等于 `record_path(root, key)`，不接受文件内容指定的绝对路径或正文路径。

根目录在读调用中不存在时返回空；首次写入时创建 `playbooks/`。目录不可读、环境配置缺失等应返回错误，不冒充“没找到”。

### 2.2 记录格式

使用 **YAML frontmatter，plan 正文内嵌**。整条记录一次替换，不再创建 `plans/` 或正文指针。

```yaml
---
schema: 1
key: qq@9.9.22
app: QQ
version: "9.9.22"
updated: "2026-11-08"
verified_with: winmcp 0.1.0
plans:
  - id: B
    summary: 读取当前窗口已暴露的命名控件
    cost: 依赖应用开启无障碍；读取耗时需要现场测量
    uses_foreground: false
    reviewed: false
    proven: false
    body: |
      ## 步骤
      1. see(hwnd, with_tree=true)，检查 timed_out 和命名控件。
      2. 本方案只读；点击、重启和切前台需要另行判断权限。
      ## 未解决
      尚未证明能够读取虚拟化列表中未渲染的项目。
---
```

除首尾独占一行的 `---` 外，内容全部属于 frontmatter；末尾只允许空白。`body` 用多行字符串保存 Markdown。`verified_with` 可省略，其余示例字段必填；普通记录 `plans` 至少一项，id 不重复。`updated` 为本地日期的 ISO 字符串；已知版本和日期必须保持字符串，未知版本只允许下一段规定的 null。

唯一的版本类型例外是未定版本观察记录：`version: null`、`key: app@unversioned`。这不是一个虚构发布版本，而是明确标识“尚不能归属实际版本”的应用级观察。该记录仍能保存失败、实测与未试方向，但存储及有效 reviewed/proven/rank 永远为 false/false/0，schema 拒绝含 true 信任位的未定版本记录，approve/confirm_proven 置 true 返回 `version unconfirmed`；它不使用 see。以后确定版本时，用 remember 写入实际版本记录并保留原观察的来源与适用范围，不直接给未定版本记录升级信任。

用 `yaml.safe_load()` 解析、`yaml.safe_dump(..., allow_unicode=True, sort_keys=False)` 写入。可用 Dumper 的字符串 representer 将带换行的值写成 `|`，保持正文可读。不要手写 YAML 解析器；不要跳过坏行后继续覆盖文件。

解析后严格验证顶层及 plan 的字段、类型和必填项；布尔值只接受真正的 `bool`，不能把字符串 `"false"` 当成真，也不能接受整数代替布尔值。不执行正文里的代码或工具调用。扫描时损坏记录记入 `warnings: [{file, reason}]` 并跳过；精确读取、修改损坏目标时返回 `invalid record`，保留原文件。

### 2.3 继承记录

```yaml
---
schema: 1
key: qq@9.9.19
app: QQ
version: "9.9.19"
updated: "2026-11-08"
see: qq@9.9.22
---
```

`see` 指 **key**，不指文件名；与 `plans` 互斥。仅跟随一次：目标必须存在、合法且为普通记录。拒绝自引用、二次继承及循环；不无限追踪。

继承只复用步骤。返回 `inherits: "qq@9.9.22"`，所有派生 plan 的 **有效** `reviewed=false, proven=false, rank=0`；不要修改源记录，也不要把源版本的验证冒充成本版本验证。`exact=true` 只代表命中请求 key。

`remember` 写继承 key 时返回 `inherited record`；显式 `overwrite=true` 才将源 plans 复制为本版本普通记录，全部验证位清零，再按规则修改目标 plan。`approve` / `confirm_proven` 不得直接修改继承记录，需先用 `remember(..., overwrite=true)` 落成本版本记录。

### 2.4 内部签名

```python
def rank(reviewed: bool, proven: bool) -> int:
    return int(reviewed) + 2 * int(proven)

def recall(query: str, max_body_chars: int = 6000,
           plan_id: str = "", body_offset: int = 0) -> dict: ...

def remember(app: str, version: str | None, plan_id: str, summary: str,
             cost: str, body: str, uses_foreground: bool,
             overwrite: bool = False) -> dict: ...

def approve(app: str, version: str | None, plan_id: str, expected_revision: str,
            reviewed: bool = True) -> dict: ...

def confirm_proven(app: str, version: str | None, plan_id: str, expected_revision: str,
                   proven: bool = True) -> dict: ...

def unresolved() -> list[dict]: ...
```

`unresolved()` 仅为内部函数，不额外暴露第 16 个 MCP 工具。测试通过 patch `memory_root()` 使用临时目录，不能改真实用户记忆。

### 2.5 recall 匹配、排序与预算

1. `query.strip()` 为空：只返回 key 清单 `keys`，不返回正文，`matches=[]`、`exact=false`。
2. 输入含路径分隔符或以 `.exe` 结尾：先用 `PureWindowsPath(query).stem` 取 app，再按 app 精确匹配。不要将 `QQ.exe` 原样与 `QQ` 比较。
3. 其余输入含 `@`：按 `make_key(app, version)` 精确匹配；未命中只回退 **同名 app** 的所有版本，`exact=false`，不混入 `QQMusic`。
4. 其余：app 名 casefold 后做子串匹配；`exact=false`。`@` 两侧为空等非法 query 返回 `invalid query`。
5. matches 按 key 排序，plans 按 `(-rank, id)` 排序。rank 顺序为 3、2、1、0，不用含糊的两位数字。

查询 `app@unversioned` 时保留标记映射到 version=None，只精确读取该观察记录；没有记录时不回退成其他实际版本。查询 app 或实际版本家族回退可同时返回未定版本记录，但在对应 match 加 `version_unknown=true`，version=None、有效 rank=0；已知版本记录该字段为 false。exact 仍只表示 key 命中，不等于版本已确认。

`max_body_chars` 必须为 1–6000 的整数，默认 6000；它是**整次响应正文字符预算**。依稳定顺序分配，超出的 body 截断或为空，在对应 plan 标记 `truncated=true`，响应总 `truncated=true`。`unresolved[].text` 也从正文派生，计入同一预算；不能通过缺口字段把全文重复送回。元数据与 key 清单不计入正文预算；本轮不做分页，不承诺固定 token 数。截断方案不可当成完整操作步骤执行。

正文不能因为传输预算而永久不可读。补齐按 plan 续读：

- `plan_id=""` 时只允许 `body_offset=0`，执行上述批量召回。
- `plan_id` 非空时，query 必须是命中实际记录的精确 key；只返回该 id 的一个 plan，不做家族回退。缺失 key/id 返回 `plan not found`。
- `body_offset` 是非负整数、按 Python 字符串字符位置计数，不能用 UTF-8 字节偏移；不得为 bool。大于完整 body 长度返回 `invalid offset`，等于长度返回空片段且无下一段。
- 每条 plan 加 `body_offset`、`body_total_chars`、`next_body_offset`。先切 `body[body_offset:body_offset+剩余预算]`，未到末尾时 next 为切片结束位置，到末尾为 None。前面被略过或后面未取完时该 plan 的 `truncated=true`。
- 调用方用 `recall(key, plan_id=id, body_offset=next)` 顺序读完；每片的 revision 必须相同，变化就丢弃已拼片段并重新读取。收到所有片段后才可把方案当成完整步骤。这里只做单条正文续读，不引入整个目录的分页状态。

```python
{
    "ok": True,
    "keys": [],                       # 只有空 query 使用
    "matches": [{
        "key": "qq@9.9.22", "app": "QQ", "version": "9.9.22", "version_unknown": False,
        "inherits": None,
        "plans": [{
            "id": "B", "summary": "...", "cost": "...",
            "uses_foreground": False, "reviewed": False, "proven": False,
            "rank": 0, "body": "...", "truncated": False, "revision": "...",
            "body_offset": 0, "body_total_chars": 3, "next_body_offset": None,
        }],
        "unresolved": [{"plan_id": "B", "text": "尚未证明……", "truncated": False}],
    }],
    "exact": True, "truncated": False, "warnings": [],
}
```

未命中使用同一结构，`matches=[]`、`exact=false`。缺口从**存储的完整**各 plan.body 提取 `## 未解决` 至下一个二级标题或文末，匹配必须用 `[ \t]*` 而非会吃换行的 `\s*`；`unresolved()` 返回 `{key, plan_id, text}`。`recall` 按 key 分组，先按 plan 顺序分配 body 预算，再分配缺口 text 的剩余预算；缺口被截断或省略也设置响应 `truncated=true`。继承缺口来自源正文，但只是继承的已知限制；源方案路径从不返回给执行器。

### 2.6 写入与审核

- 新 id 自然追加；删除 `append` 参数。已有同 id 必须 `overwrite=true`，否则 `plan exists`。
- `summary/cost/body` 均为非空字符串，`uses_foreground` 必填，未知副作用写 `true`；不得默认 false。
- 新建或实际修改方案内容后，`reviewed=false, proven=false`。覆盖参数完全相同可视为无变化，保留验证位；修改其他 plan 不清零未变的 plan。
- `approve` 只改 `reviewed`；`confirm_proven` 只改 `proven`，都允许显式传 false 撤销。不存在的 key/id 返回错误，不隐式创建。
- 对 `app@unversioned` 置 true 返回 `version unconfirmed`，不写盘；历史观察可以有价值，但不能冒充已验证的具体版本方案。
- 置 true 前调用方必须取得用户对该 key/id **当前内容**的明确确认；`confirm_proven` 还需已有多次成功的记录。本轮不自动计数，不因为 rank 高便自动确认。
- `revision` 按下方函数从完整内容派生，不额外存盘。recall 的每条 plan、remember 和审核成功结果均返回它。审核输入 `expected_revision` 必填，在同一写锁内与当前 revision 比较，不一致返回 `stale plan` 且不改文件，调用方须重新读取并确认；继承结果只用于查看，不能直接审核。
- 成功写返回 `{ok: true, key, plan_id, rank, revision}`；审核成功也返回当前 rank/revision。外部不接收 `reviewed/proven` 作为 remember 输入。

```python
import json

def plan_revision(key: str, plan: dict) -> str:
    content = {field: plan[field] for field in
               ("id", "summary", "cost", "body", "uses_foreground")}
    content["key"] = key
    payload = json.dumps(content, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return sha256(payload).hexdigest()
```

验证位不进入 revision，因此单独审核两位不互相失效；正文必须用未截断内容计算。不要在用户确认后重新查询 revision 并悄悄替换 expected_revision，否则会把对旧内容的确认授给新内容。

### 2.7 方案正文必须把知识写清楚

`reviewed/proven` 只描述整条方案的审核与重复执行状态，不能代替每项观测的证据。skill 写 body 时使用以下章节；没有内容的章节写“尚未记录”，不要把未试删掉、写成失败或默认成功：

```markdown
## 目标
要完成的任务，以及什么可观测结果才算完成。
## 环境与适用条件
记录时间、app/版本及来源、exe、启动参数、窗口可见/前后台状态、
winmcp/依赖版本；原记录缺失的字段写“未记录”，不能补猜。
## 已验证步骤
逐步列工具、实际参数、返回值、效果验证与前台/光标副作用；
只在该环境验证过的步骤才能放这里。
## 已尝试但失败
列尝试、具体输入、观测或错误、当时环境、失败范围与下一步。
“这个版本此窗口未生效”不能改写成“这个 API 对所有应用无效”。
## 实测记录
原始计数/耗时/像素变化及统计口径、样本、日志或截图位置；
历史转录值和本次新测值分开，冲突数据并列，不能挑一个覆盖另一个。
## 未解决
缺什么能力、影响哪个目标、已试到哪里、下一步需要哪个接口。
## 未试方向
每项写“未验证”、思路依据、对照步骤、预期观测、代价和回退方式；
权限未满足与工具尚未实现分别标注，不得记成已试失败。
## 更新记录
这次新增、修正或证伪了什么；旧观测适用范围发生变化时保留说明。
```

覆盖正文前先读取并合并旧记录：新试验补上新环境和结果；某个猜想被证伪时移到失败记录并保留条件。只有内容本来错误、重复或已明确解决时才删对应条目，同时留下更正依据。记忆必须保存成功路径、失败路径及剩余可能性，不能只留下一个结论。

### 2.8 单文件写事务

所有写入口共享一个模块级 `threading.Lock`，必须覆盖 **读取 → 校验 → 修改 → 临时写 → 替换**，不能只锁最后一步：

```python
_write_lock = threading.Lock()
# shortcut: 一个 memory 根目录只允许单进程写；多进程写入前改用 OS 文件锁。

with _write_lock:
    # load / validate / modify 均在此锁内。
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized_record)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
```

序列化与 schema 校验先完成，才创建临时文件；唯一临时文件与目标在同目录。替换失败向调用方报错、保留旧文件。读调用依赖整文件替换，无需看到半条记录；`os.replace` 本身不能防止并发更新丢失。本轮不承诺断电后的目录持久性或服务外编辑器的并发写入安全。

## 3. appinfo.py：报告证据，不猜活动版本

```python
def app_info(hwnd: int) -> dict: ...
def _process_path(pid: int) -> str: ...
def _file_version_info(exe: str) -> dict: ...
def _active_version(exe: Path, file_version: str | None) -> tuple[str | None, str | None]: ...
```

1. 先验证正整数 hwnd 及 `IsWindow`；以 `GetWindowThreadProcessId` 取 pid。
2. `_process_path` 用 `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION=0x1000)`、`QueryFullProcessImageNameW`，动态扩大路径缓冲；`finally: CloseHandle`。为新增 ctypes API 明确 pointer-sized argtypes/restype，不能依赖默认 int 句柄。
3. `_file_version_info` 使用 `version.dll` 的 `GetFileVersionInfoSizeW`、`GetFileVersionInfoW`、`VerQueryValueW`。`\\` 下的 `VS_FIXEDFILEINFO` 给完整四段 `file_version`；`StringFileInfo` 按 `VarFileInfo\\Translation` 读取 `ProductName/CompanyName`。没有资源则对应字段为 None，不能让 `fv/info` 未初始化。
4. 仅当 **exe 实际路径**包含 `versions/<数字版本[-build]>/...` 时，才用该活动目录名中 `-` 前的完整版本，`source="program_dir"`。仅枚举安装目录不能证明活动版本，不排序选最大目录。
5. 其余使用完整 `file_version`、`source="file_version"`；仍未知时 `version=None, source=None`。不截前两段，不伪造 `unknown` 精确 key。
6. 可枚举 exe 所在目录下 `versions/`，只收录 `is_dir()` 且完整匹配 `\d+(\.\d+)+(-\d+)?` 的名称，作为 `version_candidates`。它们只供诊断，不能替换活动版本。找不到目录返回空列表，权限失败记录 warning。
7. **QQ 类启动器的补充来源（实测，2026-11-08）**：第 4 条的路径规则对 QQ 不成立——主进程 exe 就是 `C:\Program Files\Tencent\QQ.exe`，路径里不含 `versions/`。真实活动版本只出现在**子进程的命令行**里：

   ```
   --app-path="C:\Program Files\Tencent\versions\9.9.22-40824\resources\app"
   ```

   三个来源实测对照：

   | 来源 | QQ 的值 | 可否作活动版本 |
   |---|---|---|
   | 主进程 exe 路径 | `...\Tencent\QQ.exe` | 否，不含版本 |
   | `FileVersion` | `9.9.19.35469` | 否，落后于实际 |
   | 子进程 `--app-path` | `9.9.22-40824` | **是** |

   所以在第 4 条失败后、回退 `file_version` 之前，插入一步：用 `CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS)` 或 `NtQueryInformationProcess` 枚举**同一 pid 的子进程**，读它们的命令行，正则取 `versions[\\/](\d+(?:\.\d+)+(?:-\d+)?)`。

   读子进程命令行需要 `PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ`，且跨进程读 `PEB` 需要 `NtQueryInformationProcess` + `ReadProcessMemory`。**若实现成本过高**，可退而求其次：枚举 `versions/` 目录，只有存在**恰好一个**候选时才用它（`source="sole_candidate"`），并在 `warnings` 里写明「由唯一候选推断，未直接验证」。多候选时必须返回 `None`，不许猜。

   两种做法都要在返回值里如实标 `source`，让调用方知道可信度。

返回字段固定：

```python
{"ok": True, "hwnd": hwnd, "pid": pid, "name": Path(exe).stem,
 "exe": exe, "version": version, "source": source,
 "file_version": file_version, "product": product, "company": company,
 "version_candidates": candidates, "warnings": []}
```

进程已退出或无权读取 exe 返回结构化错误；exe 可读但无版本仍成功。`name` 用可执行文件 stem，ProductName 只展示。未知版本时 skill 改用 `recall(name)` 获取候选；新观测用 `remember(..., version=None)` 保存为应用级未定版本记录，不能把候选的版本信任位用于当前进程。

## 4. UIA：线程、pattern 与权限

### 4.1 在可回收的工作进程内完成桌面调用

本机已安装的 `windows-mcp 0.8.8` 提供：

```python
from windows_mcp.uia import UIAutomationInitializerInThread
```

新增 `winmcp/uia_worker.py`，为会进入 UIA 的 `see/click/type_text/key/scroll/invoke_pattern` 提供一个复用的工作进程。它也包住这些路径内的 PrintWindow 和既有同步窗口消息，避免截图或原生动作阻塞 HTTP 线程。工作进程用 `multiprocessing.get_context("spawn")` 创建，不依赖父线程的 COM 状态。

固定内部接口与进程间消息（channel 是本机 socketpair 的一端，不是 multiprocessing.Connection）：

```python
def call(action: str, parameters: dict, timeout_ms: int) -> dict: ...
def close() -> None: ...
def _worker_main(channel) -> None: ...

# 父 → 子：普通参数；action 只允许模块内的固定分发表。
{"request_id": 1, "action": "invoke_pattern",
 "parameters": {"hwnd": 123, "pattern": "ValuePattern", "target": "search",
                "method": "Value", "args": []}}
# 子 → 父：只有普通数据；截图可带 bytes，由 server 转成 Image。
{"request_id": 1, "result": {"ok": True, "result": "current text"}}
```

实施步骤不能省略：

1. 模块顶层只定义函数和状态，不启动进程，防止 Windows spawn 导入时递归建进程。父进程用一把调度锁保护 worker 与连接；一次只向 worker 发一个请求。锁用非阻塞获取，忙时返回 `worker busy, execution_state="not_started"`，不无界排队。
2. worker 先发送 `{"transport_ready": true}`，随后在其主线程进入一次下方 UIA 上下文、成功建立分派表，再发送 `{"ready": true}`。Process.start 返回后的两段启动握手共用 5000ms 等待预算；单独记录同步 start 调用的 `start_ms`，不能宣称此预算能中断 OS 进程创建本身。初始化失败或未 ready 分别返回 `worker init failed` / `worker init timeout`，不发送实际动作。transport_ready 前失败进入下文的 unavailable 状态；已收到 transport_ready 且子进程已回收时，后续调用可重建。
3. action 分发表只包含 `see/click/type_text/key/scroll/invoke_pattern`，不接收 Python 路径、eval 或用户指定的函数。执行函数和返回值转换在同一个 worker 主线程完成。
4. `see` 在 worker 中完成截图与可选 UIA 读取；worker 内部与父端解码后的结果使用 `{meta: dict, png: bytes | None}`，JSON 线上把 png 转成 `png_b64`；server 再按现有约定组装文本和 Image。`meta.elements` 在 worker 内剔除 `_el`，不能先把对象传回父进程再剔除。
5. `see(with_tree=true)` 同时补充 `native_children`，复用 `win32.children(hwnd)`，返回其已有的 hwnd/class/text/rect 普通字段，最多 `max_elements` 项，并带 `native_children_truncated`。即使 UIA 为空也提供原生子控件；消息工具由此得到具体 child HWND，不能要求 agent 猜句柄。
6. `see` 的 worker 总预算取 `max(3000, timeout_ms+1000)` ms，允许截图及转换开销，公开 `timeout_ms` 仍是树遍历预算。现有四动作总预算 8000ms；新增 invoke 的总预算由 §4.3 定义。超时边界包含分派后的执行、转换与回包，启动 ready 的时间单独报告为 `startup_ms`。
7. 父进程用下方**非阻塞 socket 帧协议**，发送、接收帧头、接收正文都受同一个单调时钟 deadline 约束。不能用 `Pipe.poll(timeout)` 后直接 `recv()`：半帧可让 recv 再次无界阻塞，send 也有同样问题。不得只给 Future 加 timeout、每次另起收发线程或任由旧调用后台继续。超过预算时 terminate **自己创建的 worker**，join 最多 1000ms，必要时 kill 后再 join 1000ms，finally 关闭 socket 和已退出 Process 的句柄；这些清理时间在执行预算之外单独报告为 `cleanup_ms`。若仍无法回收，标记 `worker unavailable`，禁止另起无限多个 worker。
8. 超时/子进程崩溃时该次请求只返回一次失败，字段见下文；后续调用可建立新 worker，但**不自动重放上一条请求**。正常退出通过 close 通知 worker、结束其上下文、join，再关闭句柄。
9. 普通 Python 异常在 worker 转为结构化错误后可继续服务；进程退出、连接断开、request_id 不符则丢弃该 worker。用 finally 释放父调度锁，避免一次错误让全部后续调用永远 busy。

不要缓存到父进程、跨线程传递或返回 `_el`、Control、Pattern 等 COM 对象。`server.py` 的同步 MCP 包装只传普通参数给 `uia_worker.call`，不能再在 HTTP 线程直接调用 UIA；公开 8 工具签名和原生优先的顺序保持不变，但 §4.5 的定位拒绝与效果报告必须修正。direct-call 单元测试自行进入 UIA 上下文，真实 MCP 测试必须经过 worker。

worker 超时返回至少包含：

```python
{"ok": False, "reason": "desktop call timed out",
 "detail": "UIA/Win32 worker exceeded its deadline and was discarded",
 "timed_out": True, "execution_state": "unknown", "effect_verified": False,
 "retry_safe": False, "worker_restarted": False}
```

父进程仍在返回前补共同前台采样字段。终止 worker 只能结束本服务的等待，不能撤销已经进入目标应用的 COM/窗口消息；先检查目标现状再决定下一步。`see` 等纯读取可由调用方决定重读，动作不得因为返回 timeout 就自动重做。单线程预算只用于正常遍历停止，进程隔离才约束卡死 provider 的资源占用；两者都要实现。

#### 4.1.1 可直接实现的有界帧协议

使用标准库 `socket.socketpair()`，spawn 时只把 child socket 传给 worker；`process.start()` 后父进程立刻关闭自身的 child socket 副本。worker 不接收 parent socket，不用 Queue/Pipe/pickle 传结果。父 socket 在首次 I/O 前就设置 nonblocking，worker 收到 socket 后也立即设置；同一时刻只有一个请求，因此不增加应用自建的收发线程。Windows spawn 传 socket 时标准库自身会使用 resource_sharer 完成句柄移交；收到 transport_ready 才能确认移交已完成。若启动在收到它之前失败，回收进程后将服务标为 sticky `worker unavailable`，本服务进程不再重建，以防反复失败积累未领取的标准库资源；重启服务才重置该状态。[S11]

32 MiB 是整帧 JSON 上限；PNG 超过 20 MiB 时在 worker 丢弃本次图片并设置 `meta.image_unavailable="IPC image size limit"`，仍返回树。小图与元数据合起来编码仍超限时也先去掉图片、重新编码结果；元数据本身仍超限才返回 `worker response too large`，不得截断帧或自动重复动作。帧头是 4 字节网络序长度；父端先检查长度，再收正文。[S9][S10]

```python
import json
import select
import socket
import struct
import time

MAX_FRAME_BYTES = 32 * 1024 * 1024

def _wait_io(channel: socket.socket, *, write: bool,
             deadline: float | None) -> None:
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        if remaining is not None and remaining <= 0:
            raise TimeoutError("IPC deadline exceeded")
        readable, writable, _ = select.select(
            [] if write else [channel], [channel] if write else [], [], remaining)
        if readable or writable:
            return

def _send_bytes(channel: socket.socket, payload: bytes,
                deadline: float | None) -> None:
    pending = memoryview(payload)
    while pending:
        _wait_io(channel, write=True, deadline=deadline)
        try:
            count = channel.send(pending)
        except (BlockingIOError, InterruptedError):
            continue
        if count == 0:
            raise EOFError("worker connection closed while sending")
        pending = pending[count:]

def _recv_exact(channel: socket.socket, count: int,
                deadline: float | None) -> bytes:
    chunks = bytearray()
    while len(chunks) < count:
        _wait_io(channel, write=False, deadline=deadline)
        try:
            chunk = channel.recv(min(65536, count - len(chunks)))
        except (BlockingIOError, InterruptedError):
            continue
        if not chunk:
            raise EOFError("worker connection closed while receiving")
        chunks.extend(chunk)
    return bytes(chunks)

def _encode_frame(message: dict) -> bytes:
    payload = json.dumps(message, ensure_ascii=True, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    if not 0 < len(payload) <= MAX_FRAME_BYTES:
        raise ValueError("IPC frame exceeds limit")
    return struct.pack("!I", len(payload)) + payload

def _recv_frame(channel: socket.socket, deadline: float | None) -> dict:
    size, = struct.unpack("!I", _recv_exact(channel, 4, deadline))
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ValueError("invalid IPC frame length")
    message = json.loads(_recv_exact(channel, size, deadline))
    if not isinstance(message, dict):
        raise ValueError("invalid IPC message")
    return message
```

父端一次请求的代码顺序必须为：锁 → 如有必要启动并收 ready → 建立执行 deadline → 编码请求并检查剩余时间 → `_send_bytes(..., deadline)` → `_recv_frame(..., deadline)` → 核对 request_id 和 result 类型 → 解码图片 → 释放锁。给 `request_id` 递增整数，不能接受上次请求迟到的帧。任何断线、非法帧、不同 request_id、执行或 IPC 超时都丢弃 worker；发送前已拒绝的输入为 not_started，发送开始后的失败保守标为 unknown。startup 5000ms 的 deadline 同样用于收 ready 帧；正常执行 deadline 从 ready 后开始，包含序列化与传输。编码/解码前后检查剩余时间；本地有限大小转换与 OS 调度无法承诺微秒级实时性，不把超时预算说成墙钟精确返回时刻。

call 在尝试锁之前及取得锁之后都检查 stopping，避免关闭与新请求交错时又发送动作；这两个检查不替代 finally 释放锁。输入编码在发送前失败要报告 invalid arguments/not_started，不需要抛弃仍健康的空闲 worker。

`close()` 先置模块级 `stopping` Event，新 call 立即返回 worker unavailable/not_started；最多等 1000ms 抢调度锁。取得锁时，在同一个 1000ms 关闭宽限期内发送 `{"action":"close"}` 并等待 worker 退出，到期执行同样的 terminate/join/kill/join。有正在运行的 call 导致取锁失败时，close 不并发触碰 socket/Process，由该 call 的 finally 看到 stopping 后完成回收。worker 设置 daemon=True 作解释器退出兜底，不能因此省略显式回收。Process.start 失败也关闭两端 socket，释放锁；两次回收后仍活则保留 Process 引用并 sticky unavailable，不再建第二个 worker。该方案没有需要强制终止的应用收发线程；半帧停住可直接到 deadline，然后回收子进程。

#### 4.1.2 worker 分派与 see 的具体拆分

把现有 `server.see` 的采集部分移成 `uia_worker._see`，server 只做调用与 MCP 内容包装。`_see` 返回前补 §4.2 的 `tree_diagnostics/limit_reached` 与 native_children，不在 server 重读树。分派表使用这些**实际参数映射**：

```python
def _make_dispatch() -> dict:
    from . import act
    return {
        "see": _see,
        "click": lambda hwnd, target="", allow_foreground=False:
            act.act(hwnd, "click", target=target, allow_foreground=allow_foreground),
        "type_text": lambda hwnd, target="", text="", allow_foreground=False:
            act.act(hwnd, "type", target=target, text=text,
                    allow_foreground=allow_foreground),
        "key": lambda hwnd, keys="", allow_foreground=False:
            act.act(hwnd, "key", text=keys, allow_foreground=allow_foreground),
        "scroll": lambda hwnd, target="", direction="down", allow_foreground=False:
            act.act(hwnd, "scroll", target=target, text=direction,
                    allow_foreground=allow_foreground),
        "invoke_pattern": act.invoke_pattern,
    }
```

`_see(hwnd, with_tree=False, timeout_ms=1500, max_elements=200)` 在父端发送前及 worker 入口都验证：hwnd 为合法正整数且不是 bool，with_tree 为真正 bool，timeout_ms 为 1–30000 的整数，max_elements 为 1–10000 的整数，均排除 bool。拒绝负数，不能让 `children[:-1]` 泄出几乎全量列表。采集顺序：验证 `IsWindow(hwnd)` → 构造 ok/hwnd/title/class → `win32.grab` → None 写 image_unavailable，否则保留 png/尺寸 → with_tree 时 `tree.read_detailed`、剔除 `_el`、补诊断与 native_children → 返回 `{meta, png}`。不能以标题为空判断不存在；合法无标题 child 窗口也需要可读。`native_children` 取现有 `win32.children` 全量枚举后前 max_elements 项，枚举也在 worker 预算之内。`tree.describe` 增加 `native_hwnd`：读取 `int(el.NativeWindowHandle or 0)`，异常回 None 并记 warning，不用 AutomationId 冒充 HWND。

`_worker_main(channel)` 的完整控制流：

1. `channel.setblocking(False)`，先发送 `{transport_ready:true}`，进入 `UIAutomationInitializerInThread()` 并成功执行 `_make_dispatch()`；异常时尝试发送 `{ready:false, detail:<异常类型与消息>}` 后退出，全部成功才发送 `{ready:true}`。两个启动消息由父端在 start 返回后的同一个 5000ms deadline 内顺序接收，不各给 5000ms。
2. 循环 `_recv_frame(channel, None)`；worker 空闲时允许阻塞等待，父进程始终负责本次 deadline。收到 close 退出上下文；收到其他 action 先核对固定表、整数 request_id 和 dict parameters，不合法则回 not_started 的结构化错误。
3. 调 `dispatch[action](**parameters)`；捕获普通异常，返回 `{ok:false, reason:"worker action failed", detail, execution_state:"unknown", retry_safe:false}`，不换路线、不重放。业务函数返回的具体拒绝/provider 错误原样保留。
4. action 为 see 且拿到 `{meta,png}` 时，检查图片大小，再转为 `{meta,png_b64}`；其余 action 只能含 JSON 普通数据。构造 `{request_id, result}` 并先 `_encode_frame`，编码/大小异常用一个短错误帧报告 `worker response too large` 或 `worker result invalid`，附 `call_completed=true, execution_state="completed", effect_verified=false, retry_safe=false`，绝不重做动作。
5. 用 `_send_bytes(channel, encoded, None)` 发送；连接错误或部分发送后失败直接退出，不在旧半帧后拼另一个错误帧。父端超时会杀死该 worker，即使 worker 正在 send 也能回收。EOF/非法帧退出；finally 关闭 child socket 并释放 UIA 上下文。

父端给 see 成功载荷补前台字段、start_ms/startup_ms/cleanup_ms 时合并进 **meta**，不能补在外层后被包装丢掉；see 失败与其他动作则直接补到结果 dict。server 对 see 成功结果解出 png 后返回 `[json.dumps(meta, ensure_ascii=False), Image(data=png, format="png")]`（无图则仅文本）；worker/采集失败返回结构化错误，不将错误字典误当作 Image。其余五个包装原样返回结果。所有包装和 docstring 同时更新，不留下 HTTP 线程直调旧 `act.act` 的旁路。

### 4.2 扩展 tree.pattern / patterns

当前依赖的 `Control.GetPattern` 接受数值 id，不接受名称。按依赖的真实 constructor 能力生成映射：

```python
from windows_mcp.uia.enums import PatternIdNames
from windows_mcp.uia.patterns import PatternConstructors

_KNOWN = {name.casefold(): (name, pid)
          for pid, name in PatternIdNames.items()}
_SUPPORTED = {key: value for key, value in _KNOWN.items()
              if value[1] in PatternConstructors}

def pattern_detailed(el, name: str) -> dict:
    known = _KNOWN.get(name.casefold())
    if known is None:
        return {"ok": False, "reason": "unknown pattern", "detail": name}
    canonical, pid = known
    if name.casefold() not in _SUPPORTED:
        return {"ok": False, "reason": "pattern not wrapped",
                "detail": canonical, "pattern_id": pid}
    try:
        getter = getattr(el, "Get" + canonical, None)
        value = getter() if callable(getter) else el.GetPattern(pid)
    except Exception as error:
        return {"ok": False, "reason": "provider error",
                "detail": f"{type(error).__name__}: {error}", "pattern_id": pid}
    if value is None:
        return {"ok": False, "reason": "pattern unavailable",
                "detail": "wrapper returned None; exposure or failure is unknown",
                "pattern_id": pid, "cause_unknown": True}
    return {"ok": True, "value": value, "canonical": canonical, "pattern_id": pid}

def pattern(el, name: str):
    result = pattern_detailed(el, name)
    return result["value"] if result["ok"] else None
```

`patterns(el)` 保留现有 `_PATTERN_NAMES` 七项探测与小写输出，逐项走该守卫；这是常用项摘要，不是完整能力清单。未知 enum 或没有 wrapper 的项不承诺支持。当前依赖虽有 `SelectionPattern2` id，但没有 constructor，须返回 `pattern not wrapped` 与 id，不能宣称“任意 pattern 都能调用”。未列出的已封装 pattern 由 `invoke_pattern` 按需探测，不给每个节点新增数十次跨进程查询。

安装的 `Control.GetPattern` 自身会吞 COMError，某些具名 getter 又调用它；因此该守卫只能保留到达本层的异常，None 的原因必须标 unknown。只有拿到明确的 provider 不支持证据时才可报告 `pattern not exposed`；不增加“None 就是未暴露”的猜测，也不重试同一次获取以伪造原因。`invoke_pattern` 调 `pattern_detailed`，兼容调用方仍用 `pattern`。

新增 `read_detailed(hwnd, timeout_ms=1500, max_elements=200) -> dict`，共用原遍历实现；旧 `read` 返回其 `(elements, timed_out)`，保留 `check.py` 等调用方的二元返回。诊断结果固定为：

```python
{"elements": [], "timed_out": False, "limit_reached": False,
 "identity_complete": True,
 "tree_diagnostics": {
     "root_status": "ok",  # 或 absent / provider_error
     "filtered_anonymous": 0, "filtered_offscreen": 0,
     "warnings": [], "warnings_truncated": False,
 }}
```

root 获取异常、GetChildren 异常、AutomationId/Name/IsOffscreen 无法读取都会影响定位完整性，设 identity_complete=false；warning 至少含 stage、异常类型、消息、已知的节点标识/深度，最多 50 条，之后置 warnings_truncated。根返回 None 记录 root_status=absent，但原因仍可能未知，不解释成“应用没有 UIA”。矩形/可选 pattern 失败记 warning；不能因为一个可选 pattern 不存在就断言整个身份遍历不完整。保留匿名/offscreen 过滤并记录数量；这只是当前可见暴露树，不代表虚拟列表全部数据。

把 `describe` 的取值拆到内部 `_describe(el, nth, diagnostics)`，公开 `describe(el,nth)` 调同一实现；让 read_detailed 能接收错误上下文，不复制另一套取值逻辑。`see` 原有 elements/timed_out 字段保留，并追加 limit_reached、identity_complete、tree_diagnostics。定位动作使用 detailed 结果，任何 timed_out/limit_reached/identity_complete=false 均在执行前拒绝 `tree incomplete`。

### 4.3 通用属性与方法入口

```python
def invoke_pattern(hwnd: int, pattern: str, target: str,
                   method: str, args: list | None = None,
                   allow_foreground: bool = False,
                   timeout_ms: int = 8000) -> dict: ...
```

`server.py` 暴露完全相同签名。不要加进 `act()` 的 action 分支，不用 `text` 兼作方法名，也不猜默认方法。

- 校验合法 hwnd；`pattern/method` 非空；`timeout_ms` 是 1–30000 的整数且不是 bool，作为整个 worker 请求预算。args 仅接受有限 JSON 标量组成的列表（数值排除 NaN/Infinity），不接收对象、指针或表达式。
- method 可为一个公共属性/方法名，或公共属性链，如 `Value`、`GetSelection`、`DocumentRange.GetText`。逐段按标识符校验，拒绝 `_` 开头、下标、括号、表达式；不能使用 eval。
- 用下方明确的只读成员表允许后台查询；表外成员按可能有副作用处理，`allow_foreground=false` 时在进入 provider 前返回 `needs_permission=true`。该参数只允许潜在副作用，不要求服务主动激活；不能按 Get 前缀猜安全，也不限制已授权调用的其他公开 wrapper 成员。
- `target=""` 明确表示根窗口，直接 `ControlFromHandle(hwnd)`；该参数仍需显式传入。其他 target 在同一已初始化线程中调用 `tree.read_detailed(hwnd, timeout_ms=3000, max_elements=600)`，用 AutomationId 精确匹配优先、再用 name 精确匹配。
- `timed_out=true`、`limit_reached=true`、`identity_complete=false` 或保守的 `len(elements)>=600` 均返回 `tree incomplete`，即使部分结果中已命中也不动作。完整读取后候选超过一个返回 `ambiguous target`，无候选返回 `no such control`；不得沿用 `tree.find()` 的首个模糊匹配执行任意方法。
- `pattern_detailed` 的 `unknown pattern / pattern not wrapped / provider error / pattern unavailable(cause_unknown)` 原样保留；有明确证据才用 `pattern not exposed`，不能混成“应用不支持 UIA”。依赖缺 wrapper 时返回枚举 id 与具体缺口，保留后续补封装的路线，不能删除 skill 中该方向。
- 属性链中间段必须是依赖中已知 wrapper 类定义的 `property`，取值仍须是受支持 wrapper；受信类型取 `tuple(PatternConstructors.values()) + (Control, TextRange)`（使用依赖的实际类，不接受仅同名对象）。禁止经 `pattern`、`Element`、`textRange` 等字段进入原始 COM。中间方法不调用，禁止传入或返回原始 IUnknown。
- 最后一段是公开 wrapper 方法时执行 `member(*args)`；是公开 property 时要求 args 为空再读取。用 `inspect.getattr_static` 检查类描述符后才访问实例，不能仅凭 hasattr/getattr 就允许任何公开对象导航。
- `args=None` 等同 `[]`；参数错误、属性异常和 COMError 分别返回 `invalid arguments`、`member unavailable`、`provider error`。调用失败不改走其他方法、真实鼠标或自动重试。
- 保存真实返回值，按照 §4.4 转成普通数据。`Expand/Collapse` 等 wrapper 可能吞异常并返回 False：已知动作方法返回 False 时 `ok=false, reason="provider reported false", call_completed=true`；读取 `Value/IsSelected/...` 得到 False 则是合法查询结果。动作集合在本地常量中明确列出 Invoke/Toggle/Select/Expand/Collapse/SetValue/Scroll/DoDefaultAction/Move/Resize/Close，不按名字前缀推断。
- 其余调用完成返回 `act._done(..., route="uia:<canonical-pattern>", ...)`，追加 `call_completed=true, result=<普通数据>, result_truncated, effect_verified=false`。调用完成只证明拿到结果，业务效果仍须验证。

`WindowPattern.Close` 可以关闭窗口，Invoke/SetFocus 等可能夺焦。保留通用方法出口意味着调用方仍须按用户任务授权执行；工具本身不把它们认证为无害。[S2]

只读策略表使用 canonical pattern 与**完整成员路径**精确匹配：

```python
_READ_ONLY_MEMBERS = {
    "ValuePattern": {"Value", "IsReadOnly"},
    "RangeValuePattern": {"Value", "IsReadOnly", "Minimum", "Maximum",
                          "SmallChange", "LargeChange"},
    "SelectionPattern": {"GetSelection", "CanSelectMultiple", "IsSelectionRequired"},
    "SelectionItemPattern": {"IsSelected"},
    "TextPattern": {"DocumentRange.GetText", "GetSelection", "GetVisibleRanges",
                    "SupportedTextSelection"},
    "ScrollPattern": {"HorizontallyScrollable", "VerticallyScrollable",
                      "HorizontalScrollPercent", "VerticalScrollPercent",
                      "HorizontalViewSize", "VerticalViewSize"},
}
```

属性不接收 args；无参查询只接收空列表；GetText 的 maxLength 必须为 1–6001 的整数且非 bool，拒绝 -1 的无界取全文。调用显式 GetText 后若返回长度达到请求上限，加 `possibly_truncated=true`；按 Windows UTF-16 code unit 长度作保守检查，不能因为结果未占满 6000 个 Python 字符就声称取得全文。`possibly_truncated` 与传输 `result_truncated` 分开：前者标 API 取文上限，后者标本服务投影截断，任一为真都不能当完整文本。表中成员仍可能由有缺陷的 provider 实现，照样受 worker 总超时与副作用报告约束；若某个应用的已测 getter 会夺焦，memory 对该路线填 uses_foreground=true，并停止把它当后台方案复用。

### 4.4 UIA 结果投影与可执行案例

实现 `_plain_result(value, budget)`，所有读取和转换仍在 worker 的 UIA 上下文中。固定总文本上限 6000 字符、集合总条目上限 100、嵌套深度上限 4；这些是传输边界，不截断持久化知识。达到上限置 `result_truncated=true`，不得把片段称作完整数据。

| 返回类型 | 转换规则 |
|---|---|
| None/bool/int/有限 float/str | 保留原类型；字符串消耗总字符预算，不能用 str() 抹掉类型 |
| list/tuple、仅字符串 key 的 dict | 在总条目/字符/深度预算内递归投影，保持顺序；遇未知类型按下行失败 |
| UIA Control | 调 `tree.describe` 转元数据并剔除 `_el`；保留 type/name/automation_id/rect/原生句柄等已取到的普通字段 |
| UIA TextRange | 在原线程执行 `GetText(剩余字符预算+1)` 探测截断，只返回有界 text、truncated、possibly_truncated。达到 API 请求上限时后者必为 true，即使未耗尽 Python 字符预算；不把 TextRange 传给父进程 |
| 原始 COM 或其他对象 | 返回 `result unsupported`，带 `call_completed=true, execution_state="completed", effect_verified=false`；说明调用可能已执行，不得自动重试，不能丢结果后回一个空成功 |

以下不是未来猜想，必须作为待实现工具的行为案例完成：

```python
# name/AutomationId 需取自当前窗口；前台授权参数须来自已有任务授权。
invoke_pattern(hwnd, "ValuePattern", "search", "Value", [], True)
invoke_pattern(hwnd, "TextPattern", "editor", "DocumentRange.GetText", [4096], True)
invoke_pattern(hwnd, "SelectionPattern", "members", "GetSelection", [], True)
invoke_pattern(hwnd, "ExpandCollapsePattern", "folder", "Expand", [], True)
```

前三条分别验证字符串/属性、文本范围链和控件列表投影；第四条验证动作 False 不能误报成功。`SelectionPattern2` 当前缺 constructor 的事实照实报告，后续补适配时应使用依赖已有的 wrapper 与接口映射并添加独立测试；不修改第三方全局注册表来让一次调用侥幸通过。

### 4.5 现有动作也必须拒绝不确定目标、如实报告效果

本节是兼容签名下的必要修正，不能只在 skill 写“不要盲点”而保留 MCP 的危险分支：

1. `act._child` 被 click/type 两处调用。共同修正为按“精确 text → text 子串 → class 子串”的原优先级找候选，**每层仅一个才命中，超过一个立即 ambiguous target**，不能取第一项或继续降级。空 target 仅当可操作的原生候选恰好一个时可用；多个时拒绝。拒绝时发送消息计数为零。
2. 原生未命中、获前台授权之后，非空 target 的 UIA 路线用 read_detailed 检查完整性。候选层次为精确 AutomationId → 精确 name → name 大小写不敏感子串，每层同样要求唯一；仅通用 invoke_pattern 保持 §4.3 的纯精确规则。不完整、歧义、找不到分别返回 tree incomplete/ambiguous target/no such control，不能激活后再盲找，不能点窗口中心。
3. click 没有原生唯一目标且 target 为空时返回 `target required`。删除末尾 `win32.center(hwnd)` 的兜底点击；已唯一定位的元素可按原顺序尝试 Legacy/Invoke/Toggle/SelectionItem，最终只有矩形有效且已授权时才能用元素自身中心。矩形无效返回 `control has no clickable area`。不新增坐标点击参数；确需视觉交互时由 skill 报出具体能力缺口。
4. 保留“原生优先、Legacy 仍在 allow_foreground 门之后”的路由顺序，不把现状改写成默认后台 Legacy。点击消息/动作返回与业务效果分开：BM_CLICK 检查 PostMessageW 是否成功，只可报告 queued/effect_verified=false，不能忽略 API 的失败返回。

   既有 Legacy/Invoke/Toggle/Select/SetValue 同样保存 wrapper 返回值，按 §4.3 区分动作False与合法查询False。仅当某个 pattern 不存在、尚未调用动作时才可继续原有候选顺序；已经调用后抛错、返回False或读回不可用时，先返回真实状态供 skill 核对，不能在一次调用内悄悄换另一条有副作用路线，避免重复点击或输入。ValuePattern 不存在时才进入已授权的真实键入路径。
5. 原生 type 使用 §5 的内部托管同步文本 helper `_set_text_managed(hwnd, text, timeout_ms, max_chars)`，替换现有无界 SendMessageW，复用同一缓冲区、结果和剩余预算规则；保留该路线的现有权限行为，不能调用公开 post_message 包装后因 setter 权限门而改变原生 type 的默认行为。该内部 helper 只处理已经由调用入口验证/授权的数据，不负责决定授权。UIA SetValue 或真实键入后，若取得的字符串与目标不同，才报明确 readback mismatch；pattern 缺失、Value=None、getter 异常表示 `effect_verified=false, verification_reason="readback unavailable"`，不能宣称“什么都没写入”，也不能宣称已验证成功。需要其他语义/视觉证据时交给 skill，不自动重复输入。
6. 执行真实键鼠前检查 `IsWindowVisible`、非最小化及 foreground==目标 hwnd；可以复用 launch.is_shown，但不能仅相信 win32.activate 的 True。若原生或 UIA 已可能产生动作，之后失败应带 execution_state=unknown/completed 的实际证据，不能报 not_started。不得在无法确认目标焦点时调用 SendKeys。
7. `key` 复用现有 `_normalise_keys`：Ctrl+s、^s、Enter 等转换，1+1、a+b 保持文本语义；不另写一套键语法。scroll 的目标非空且未命中时也不能退回根窗口；只有显式空 target 才表示根级滚动，效果用位置/新增项目验证。

8. 修正既有 scroll 的枚举参数：当前 `sp.Scroll(0, -3 if text == "up" else 3)` 中 0 是 LargeDecrement，会意外请求横向滚动；-3 不是有效枚举。使用以下代码，direction 先严格限制为 up/down，保留实际返回值并按动作False处理，不把没有异常当成功：

```python
from windows_mcp.uia.enums import ScrollAmount

vertical = (ScrollAmount.LargeDecrement if direction == "up"
            else ScrollAmount.LargeIncrement)
reported = sp.Scroll(ScrollAmount.NoAmount, vertical)
```

枚举事实来自本机依赖源码：LargeDecrement=0、SmallDecrement=1、NoAmount=2、LargeIncrement=3、SmallIncrement=4。此处是代码核对，**未证明历史 QQ 失败由此造成，也未验证改后能够滚动**；原失败、GPU等未试方向照常保留。测试 mock provider 核对上下滚动的两个精确参数、False返回及滚动位置不变，不固定真实应用效果。

所有分支补 §1.3 的前台观测；`effect_verified` 只能根据本次可用证据设置。新诊断/定位逻辑集中到共享 helper，别在四个动作中复制并产生不同的“唯一”规则。

### 4.6 启动隐藏必须先证明窗口归属

当前 launch 的两段循环会隐藏观察期内**所有**新出现的可见顶层窗口，还会无条件争回前台。这个已核对的实现边界不能只改成一条免责声明；本轮必须修正，否则一次正常启动可能干扰同时出现的无关窗口。保留 open_app 公开签名、实际启动能力和 hidden_windows 原有 hwnd/class/title/still_visible 字段，按以下步骤修复：

1. 启动前用内部 EnumWindows 枚举全部顶层 HWND（包括隐藏窗口），形成 baseline；不能用仅含可见窗口的 windows() 证明“启动前不存在”。保存启动前前台 HWND 及其进程身份。
2. `Popen(..., shell=False)` 成功后，立即用 OpenProcess/GetProcessTimes 保存启动器的 `(pid, process_created_at)` 及持有的进程句柄；新句柄需在 finally 关闭。复用 appinfo 的进程查询/ctypes 声明，时间采用原始 FILETIME 整数以避免浮点丢失。无法读取创建时间就标未知，不猜。
3. 用 Toolhelp 进程快照取 th32ParentProcessID，只将已核验父进程身份、创建时间/时序相容的观察到的子孙纳入 owned 集合；期间持有相关进程句柄。PPID、相同 exe、窗口标题或“启动后出现”单独都不构成归属证明。父链漏采、PID复用、权限拒绝保持未知。[S13][S14]
4. 两段循环共用 `_owned_window(hwnd, baseline, owned)`；每次隐藏前重新检查 HWND 当前PID/创建时间、非baseline。仅确认归属才 SetWindowPos，并检查API返回及实际可见状态；失败留错误。不相关或未知窗口不隐藏。只有当前前台也归属 owned，且原前台身份仍相同、仍可见非最小化时才回交前台；不能打断用户主动切到其他应用。
5. 单实例转交、URL/快捷方式/UWP broker 等没有可核验归属链时，启动请求仍可成功，返回 unknown 的候选供 skill 继续 windows/see 定位；不隐藏既有窗口、不杀进程、不伪造“已后台启动”。当前 Popen 不具备通用 ShellExecute/URL/LNK 解析契约，不能凭输入扩展名承诺此能力。accessibility flags 仍保留，实际是否由目标采纳另行核对。

返回保留原字段，追加 `target_window_confirmed: bool`、`visibility_control: "applied" | "partial" | "unconfirmed" | "not_requested"`、`window_candidates: list`、`warnings: list`。hidden_windows 中追加 pid/process_created_at/ownership_basis（direct_process 或 observed_descendant）/hide_succeeded；pid 顶层字段明确仍是启动器PID。applied只描述已确认窗口上的隐藏结果，不保证应用永不重新显示；部分隐藏失败用partial，无归属证据用unconfirmed，show=true用not_requested。候选最多200项，带ownership=unknown/reason和候选截断标记，不把无关新窗口混成已确认目标。

这项修复扩大可靠定位能力，不能以禁止单实例应用启动来规避归属问题。GUI 验证同时创建本轮目标与一个无关测试窗口，后者的隐藏/激活调用计数必须为零；再覆盖已证实子进程、转交、查询拒绝与PID/HWND复用的mock分支。

## 5. post_message：有界同步、异步入队与托管文本

在 `win32.py` 实现，`server.py` 同名包装：

```python
def post_message(hwnd: int, msg: int, wparam: int = 0, lparam: int = 0,
                 allow_unsafe: bool = False,
                 allow_foreground: bool = False, wait: bool = True,
                 timeout_ms: int = 1000, text: str | None = None,
                 max_chars: int = 4096) -> dict: ...
```

保留原稿的同步查询能力和工具名称，分支由 wait 决定：`wait=true` 用 **SendMessageTimeoutW**，`wait=false` 用已有 PostMessageW。不要使用无界 SendMessageW。WM_GETTEXT/WM_SETTEXT 由服务托管缓冲区，不能为了可靠性把文本读写和标量查询一并删掉。

### 5.1 ctypes 声明与同步返回值

在 `win32.py` 声明一次，不能省略输出指针或沿用默认 int：

```python
from ctypes import wintypes

DWORD_PTR = ctypes.c_size_t
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    wintypes.UINT, wintypes.UINT, ctypes.POINTER(DWORD_PTR),
]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002
SMTO_ERRORONEXIT = 0x0020

def _send_scalar(hwnd: int, msg: int, wp: int, lp: int,
                 timeout_ms: int) -> tuple[int, int, int]:
    output = DWORD_PTR()
    ctypes.set_last_error(0)
    completed = user32.SendMessageTimeoutW(
        hwnd, msg, wp, lp,
        SMTO_BLOCK | SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT,
        timeout_ms, ctypes.byref(output),
    )
    error = ctypes.get_last_error() if not completed else 0
    result = ctypes.c_ssize_t(output.value).value
    return int(bool(completed)), result, error
```

API 自身非零表示消息返回；真正的消息结果来自 output，可合法为 0 或 -1。转换为有符号指针宽整数，不能把 CB_ERR=-1 回成 18446744073709551615。不要使用 `SMTO_NOTIMEOUTIFNOTHUNG`，它会放松时间上界。[S5]

### 5.2 校验与权限顺序

1. hwnd 必须为存活的正整数窗口，拒绝 `0`、`-1`、`0xffff`（广播）等特殊句柄；不允许线程消息或广播。
2. msg 为 `0..0xffff` 整数；wparam 为指针位宽无符号整数，lparam 为指针位宽有符号整数；`timeout_ms` 为 1–30000，`max_chars` 为 1–65536，均不接受 bool 或溢出。text 只允许用于下节 WM_SETTEXT，不提供外部缓冲区地址。
3. 同步模式拒绝属于**调用该 API 的当前进程 PID** 的窗口，避免同输入队列直接执行忽略 timeout 和同进程缓冲区超时寿命问题；worker 内部文本 helper 也要以 worker 当前PID检查。服务的测试窗口必须在另一个进程。`wait=false` 也不允许托管指针消息。[S5][S8]
4. `WM_COPYDATA=0x004A`、`WM_DROPFILES=0x0233` 等尚无托管封送实现的 payload 消息返回 `message payload unsupported`；不能用 allow_unsafe 绕过。WM_SETTEXT/WM_GETTEXT 严格走下一节专门分支。
5. 标量已知集合：WM_NULL=0x0000、WM_GETTEXTLENGTH=0x000E、BM_CLICK=0x00F5、BM_GETCHECK=0x00F0、CB_GETCURSEL=0x0147、LB_GETCURSEL=0x0188、WM_KEYDOWN/UP/CHAR=0x0100/0x0101/0x0102、WM_LBUTTONDOWN/UP=0x0201/0x0202、WM_MOUSEWHEEL=0x020A。集合外需要 `allow_unsafe=true`；调用方必须确认具体消息不携带指针或跨进程句柄，不能仅凭一个整数判断地址安全。
6. WM_NULL 及上述只读查询可不占用前台；BM_GETCHECK/CB_GETCURSEL/LB_GETCURSEL 先检查 class_name(hwnd).casefold() 分别含 button/combobox/listbox（兼容 WindowsForms10.BUTTON 等类名），否则返回 `control class mismatch`。setter、点击、键鼠和未知消息默认返回 `needs_permission`，需要 `allow_foreground=true` 才可继续；这个授权不要求服务主动激活窗口，也不替代具体业务授权。
7. 读取类消息要求 `wait=true`，否则返回 `query requires wait`，不能把查询入队却丢弃答案。未知消息的原始 result 不解释成业务成功；已知类和消息的特殊结果见下节。

### 5.3 文本缓冲区与消息语义

WM_GETTEXT 与 WM_SETTEXT 只接受跨进程、同步的系统消息封送路径；服务不暴露指针，缓冲区在整个 API 调用期间有本地引用。系统对这些消息的封送负责目标侧临时数据的寿命；这条保证不能推广到自定义消息或同进程跨线程消息。[S6][S7][S8]

| 消息 | 输入、缓冲与返回要求 |
|---|---|
| WM_GETTEXT=0x000D | 要求 text=None 且外部 wparam/lparam 均为 0。服务分配 `ctypes.create_unicode_buffer(max_chars+1)`，内部 wp=容量、lp=buffer 地址。完成后返回 text、result、capacity、possibly_truncated；result=0 表示空串也可成功，达到 max_chars 只说明可能截断。超时不读缓冲区，不返回残片。 |
| WM_SETTEXT=0x000C | 要求 text 为字符串（允许空串）、无内嵌 NUL、可严格编码为 UTF-16，长度不超过 65536 个 UTF-16 code unit；外部 wp/lp 均为 0。服务创建字符串缓冲区，内部 wp=0、lp=地址。result=0 表示拒绝；标准 ComboBox/ListBox 的 -1/-2 等错误码也返回 `control rejected text`，不可把所有非零值当成功。其余返回仍需同 HWND 的 WM_GETTEXT 读回比较。 |
| WM_GETTEXTLENGTH=0x000E | 只返回字符长度，可能与随后读到的内容因并发编辑不同；不据此宣称已取到正文。 |
| BM_GETCHECK | 0/1/2 是合法状态值，不以 0 判断运输失败。 |
| CB_GETCURSEL / LB_GETCURSEL | -1 表示无选择，属于已解释查询结果，返回 `selection_index=-1`；不把 -1 转成巨大无符号数。 |

UTF-16 code unit 与 Python len 不等价，例如 emoji 占两个 code unit；容量和长度字段写明计数单位。获取文本的缓冲区可在边界处截断代理对，结果转成可编码的 Unicode（孤立代理项用 U+FFFD 并标 `text_repaired=true`），不得让 JSON 序列化崩溃；保留原 result 作为 API 的 code unit 数。

WM_GETTEXT 返回数必须落在 0..容量-1，超出则 `invalid message result`，不据此读取越界内存。SS_ICON 样式的 Static 在特定条件下可能写入图像句柄，SS_BITMAP 等非文本 Static 也不返回普通字符串；这些分支返回 `control payload unsupported`，不把缓冲区解释为文本。Scintilla 等自定义控件也不保证实现标准 WM_GETTEXT/SETTEXT，应保留返回与验证结果并切换其公开接口，不能按类名就承诺可写。[S6][S7]

WM_SETTEXT 的读回也受同一次 timeout_ms 总预算限制：用单调时钟减去首个 setter 耗时，把剩余预算交给一次读取，不能每次验证重置完整预算。**内部验证缓冲区按输入的 UTF-16 单位数 n 分配 n+2 个 wchar**，可读取 n+1 单位以检测“新文本后还有尾部”；内部 getter 支持 capacity_units<=65538，不经公开 max_chars<=65536 的预览校验入口。不能拿默认4096单位的截断预览比较65536单位的输入。返回预览另按 max_chars 个UTF-16单位切分（不是Python len）并带 possibly_truncated；比较用完整验证结果，不用预览。读回触及内部容量上限时只报 `verification_reason="readback incomplete"`、effect_verified=false，不能假报 mismatch；完整字符串确实不等时才 `ok=false, reason="text readback mismatch", execution_state="completed"`。

写完无剩余预算时返回 `ok=true, delivery="returned", effect_verified=false, verification_reason="budget exhausted"`，不自动重写。读取超时或其他原因无法验证时，保留 setter 的 result/delivery/call_completed，另加 verification_reason、verification_error；不能将已返回的 setter 改写成未发送。比较按 UTF-16 规范编码的内容进行，孤立代理项修复只影响返回预览，不拿修复后的不同字符串证明写入失败。

### 5.4 完成、失败和超时必须可区分

- 同步完成：`{ok: true, delivery: "returned", result: <signed int>, call_completed: true, effect_verified: false, ...foreground_fields}`；可追加 text/选择状态。只有本次明确读回符合目标时才把 effect_verified 置 true。
- 异步入队：PostMessageW 非零只回 `{ok: true, delivery: "queued", effect_verified: false, ...foreground_fields}`，不伪造 result。迟到的消息可能在前台采样之后产生副作用。[S1]
- API 返回 0：先前已清理 LastError；error=1460 时 `reason="message timed out"`，error 非零其他值回 `message delivery failed` 与错误码，error=0 回 `message delivery failed`，不能杜撰超时原因。
- 同步失败或超时都不假定动作已取消：`execution_state="unknown", effect_verified=false, retry_safe=false`。目标可能尚未取消息，也可能已经进入 WndProc 并继续执行；调用方不能可靠区分，**禁止自动重发**。[S8]
- 任何分支都补共同前台字段。拒绝发生在发送前则 `execution_state="not_started"`；发送已完成但验证失败则为 completed，不能说“什么也没发生”。

```python
# 先 see(parent, with_tree=True)，从 native_children 取得 child_hwnd。
post_message(child_hwnd, 0x000D, wait=True, max_chars=4096)
post_message(child_hwnd, 0x000C, wait=True, text="中文🙂", allow_foreground=True)
post_message(button_hwnd, 0x00F0, wait=True)
post_message(combo_hwnd, 0x0147, wait=True)
post_message(button_hwnd, 0x00F5, wait=False, allow_foreground=True)
```

鼠标参数由调用方按 Win32 约定打包：WM_LBUTTONDOWN/UP 的 lparam 是**客户区**坐标；WM_MOUSEWHEEL 的 lparam 是**屏幕**坐标、wparam 高字是有符号滚动量（每格 120）。截图坐标必须先做相应转换，不能直传。`0x0233` 是 WM_DROPFILES，不是 WM_POWERBROADCAST；删除原稿“harmless”条目。[S3][S4]

## 6. MCP 记忆包装与 skill

`server.py` 为 `recall/remember/approve/confirm_proven` 使用 §2.4 的精确签名并直接转发。recall 的 docstring 说明空 query 只列 key、继承/家族命中不能代表本版本验证；remember 说明覆盖会重置被改方案的信任位。不要在包装层再复制一套排序或存储逻辑。

### 6.1 skill 的能力地图与探测步骤

新建 `skills/windows-app-automation/SKILL.md`，正文包含以下完整规则；设计稿保留理由与完整实测证据，不复制第二套接口契约：

```markdown
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
```

以上代码块为完整、可独立分发的 SKILL.md 内容，正文模板和必要的历史起点已内嵌，不依赖未随安装分发的交接稿。skill 保留跨应用的探索方法、分支与已知实验方向；某软件某版本的实际结果归 memory。完整原始转录和来源边界在仓库设计稿 §7，供审阅追溯，不是安装后运行的必需依赖。静态 skill 携带的起始假设不得升级为已证实方案，不自动把历史条目种成 rank>=2 的记忆。

### 6.2 skill 源码与分发的历史现场记录

源码唯一位置为 `skills/windows-app-automation/SKILL.md`。原交接稿记录：DSH 的 `~/.dsh/skills/` 为实体目录；Codex 的一个现有 relay-imagegen skill 使用指向 `C:\Users\32677\source\relay-imagegen` 的 Junction；Claude 的 `~/.claude/skills/` 为实体复制。它们是原稿现场状态，**本次未重新核验**，不能推断三个客户端机制相同。

实施部署时先读当前目标目录/链接目标，再选择复制或链接到本仓库 skill 源码目录；复制方式必须同步更新，链接方式核验目标存在。以客户端重新加载后的实际发现结果为准。不要为了套用历史示例覆盖已有目录，也不要把运行时包副本当成 skill 唯一源。本轮文档修改不操作用户全局 skill 目录。

## 7. 实施顺序与部署

1. 完成 memory、严格 schema、未定版本记录、正文续读、revision 与临时目录行为测试。
2. 完成 app_info；实现 post_message 的同步标量、异步投递、托管 GET/SETTEXT 和同预算读回。先用 mock 验证参数、错误与指针宽度，不接触真实用户窗口。
3. 完成 tree 的诊断入口/原生句柄、pattern 守卫、invoke_pattern 的属性链/投影；修正现有动作的歧义、中心点击、文本验证、滚动枚举、激活检查及启动窗口归属。测试所有拒绝分支在发送动作前发生。
4. 完成 worker 的 spawn/握手、非阻塞帧、deadline、busy、异常回收、重建及 close。纯 IPC 测试使用测试模块的假 worker，不需要真正 UIA；再验证实际 MCP 包装全部经过 worker。
5. 注册 7 个工具，核对 15 项工具的 schemas/HTTP 请求和生命周期；以 FastMCP lifespan 的 finally 调 uia_worker.close，确保停止服务会回收本服务 worker。加入完整独立 skill，更新 README/INSTRUCTIONS，删除过度诊断、默认后台 Legacy、所有 UIA 必夺焦和“用户离开就可执行”等失实描述。
6. **修正 check.py 测试清理**：当前代码会关闭所有 class 含 Notepad 的窗口。仅允许清理本轮创建且 PID/HWND 已跟踪的测试窗口；验证句柄仍属于该进程，不能按类名扫用户窗口。若无法可靠跟踪新记事本实例，就跳过该应用用例并报告，不能批量关闭。
7. 在隔离桌面或确认安全的会话运行 GUI 集成回归；最后才按已授权范围部署。

推荐验证命令（仓库根目录，venv 路径按实际安装调整）：

```powershell
$taskPython = "$env:LOCALAPPDATA\winmcp\.venv\Scripts\python.exe"
& $taskPython -m unittest discover -s tests -v
# 仅在第 6 步清理问题修正后运行：
& $taskPython -m winmcp.check
```

editable 安装和运行目录不是两个代码真相。**不要再 Copy-Item 整个包“保险同步”**。部署前先核对任务配置与 import 来源：

```powershell
Get-ScheduledTask -TaskName winmcp-helper | Select-Object -ExpandProperty Actions
Push-Location "$env:LOCALAPPDATA\winmcp"
try {
    & $taskPython -c 'import winmcp.server; print(winmcp.server.__file__)'
    & $taskPython -m pip show winmcp
} finally {
    Pop-Location
}
```

若导入不指向工作仓库，先检查任务工作目录是否有旧 `winmcp/` 包遮蔽 editable 安装。备份该副本后调整任务工作目录至仓库，或移走已确认过时的副本；只重新安装 editable 不能消除当前目录的遮蔽。随后在目标 venv 安装该仓库及声明依赖，并从实际任务工作目录复核导入路径。

改代码/依赖后需重启实际监听服务；同时检查 python.exe 和 pythonw.exe，仅停止确认属于该服务的 PID。用任务状态、8765 端口的拥有 PID、MCP 初始化与工具清单一起判断启动成功，不能只看端口计数。不要在交接脚本里自动 push、点击凭据账户或写本机代理。

### 7.1 历史操作诊断必须保留，但不能变成自动动作

以下历史记录来自基线交接稿 §8.2/§8.3、设计稿和 README；本次未重新启动任务、操作凭据窗口、测量代理或更改 ACL。代码核对仅说明现有分支，不替代现场复测。

| 触发或观测 | 历史事实、现有边界与下一步 |
|---|---|
| 启动命令报 4294967295 | 原稿记录 `Windows Job runner exited with exit code 4294967295` 时任务可能已启动。分别只读检查实际任务 Action/状态、8765 的 owning PID、进程命令行及 MCP 握手，不因工具层退出码就重复启动。 |
| Git 操作停滞 | 历史凭据窗口为 `Select an account`、`Avalonia-*`，标题无 git，PID 与 Git 不同；原稿称遇到三次。windows/see 可辅助确认，但不按旧坐标或自动选首个账户，须核对本任务所用账户与已有授权。同步修正当前 INSTRUCTIONS 直接建议点账户的文案。 |
| 网络/代理异常 | 原稿记录 Git 代理 `127.0.0.1:7890`，7897 当时不可用；这是历史值。读取当前配置及来源、相关环境变量与监听状态，区分代理故障与认证等待；不自动改全局配置。 |
| 无控制台或无日志 | 当前 install.ps1 注册交互会话的 pythonw.exe；run-helper.ps1 另有隐藏 python.exe 并重定向 helper.out.log/helper.err.log 的路径。检查实际任务动作，不能假定 runner 或这两个日志正在使用；服务需在有目标窗口的用户桌面会话内。 |
| 截图 None/空白 | 历史提到 GPU overlay、保护内容、最小化；当前 grab 还会在无尺寸、DC获取失败、PrintWindow/GetDIBits失败和单色图判断时回 None。分别记录截图与树结果，不能凭统一 image_unavailable 文案确诊 GPU；树可用就继续语义路线。 |
| 不同 venv 截图差异/ACL | README 曾归因于解释器目录 ACL，并把 S-1-4-* 称为 capability SID；微软资料给 capability SID 的前缀为 S-1-15-3，因此旧分类有误，现场因果亦未复测。[S12] 保留完整解释器路径、ACL、真实 API 错误与可比环境，不自动删除 ACE，不承诺换目录必定解决。 |
| UWP 壳有树、内容无树 | 历史某些 ApplicationFrameWindow 只暴露标题/输入壳，内容在其他 CoreWindow。检查子 HWND/内容窗口及身份关联，不将壳空树泛化为整个 UWP 无能力；布局仍需现场确认。 |
| 输入后 Value=None | 历史 Chromium 中存在实际已有文字但 Value 返回 None，以及 setter 静默无效两种观察。现有 act 在 pattern 有但值None时可能报失败、无pattern时反而可成功；按 §4.5 统一成“无法验证”与“完整读回不符”，用其他可用证据核对。 |
| 隐藏激活报告成功 | launch.force_foreground/is_shown 已检查可见、非最小化；act 所用 win32.activate 在 foreground 相同时直接 True，不能把一个入口的 guard 泛化给另一个。按 §4.5 修正真实键鼠前的验证。 |
| getter 缺失/异常 | GroupControl 等没有所有具名 getter，裸调会 AttributeError。现有守卫与依赖仍吞部分异常；按 §4.2 留诊断或标原因未知，不把 None 当未暴露。原稿“已修三次”是历史描述，不当本轮回归证据。 |
| 隐藏启动找不到窗口 | open_app 的 hidden_windows 可定位返回的隐藏 HWND；windows 只枚举可见顶层窗口。现有隐藏循环会处理观察期内新出现窗口，并非只按新PID过滤；不能保证不影响同时出现的其他窗口。保留 foreground_contests 和前后采样，但两点采样不能证明过程中从未夺焦。 |

这张表用于给实施者和后续 skill 维护提供诊断入口。涉及真实环境的值不能直接种入已证明记忆，变更应用、账户、任务配置或 ACL 仍按当前任务授权和现场证据处理。

## 8. 验收矩阵

单元测试不接触真实 memory、不关闭用户窗口。测试成功要以输出为证，不以断言数量或无临时文件代替行为验证。

| 范围 | 必测行为 |
|---|---|
| 身份 | 路径含活动版本时取完整版本；只有候选目录不冒充活动版本；完整 FileVersion；无版本、权限拒绝、进程退出 |
| 目录 | 版本名但非目录、setting.json、多个版本均不误判；验证 9.9.9/9.9.22/10.0.0 不做字符串最大值推断 |
| 记录/schema | 临时目录读写 round-trip；中文 app、`../`、保留名均不越过根目录或碰撞；路径摘要与内容 key 互相校验；坏 YAML/日期被解析成对象/错误 bool/未知 schema/重复 id 拒绝覆盖 |
| 未定版本 | version=None 保存到 app@unversioned 且可 recall；字符串 unversioned 不冒充版本；有效 rank=0，存储真信任位拒绝；approve/confirm_proven 的 true 返回 version unconfirmed；后续实际版本另存，旧观察保留 |
| 匹配 | 精确 key、同 app 回退不混入 QQMusic、Windows 路径、exe stem、子串、空 query、未命中成功；unversioned 只精确读本记录、不家族回退 |
| 预算/续读 | 全响应 body+unresolved.text 不超预算；被截断计划有 next_body_offset，按稳定 revision 续读可恢复完整正文；中途内容变化不得拼接；非法 offset/非精确 key 续读拒绝；offset==长度可正确结束 |
| 排序/信任 | 全部四组合得到 3/2/1/0；同分稳定；修改 body 后清零；审核两位独立更新和撤销；旧 revision 的审核不能给并发覆盖后的内容置位 |
| 并发/失败 | 两线程同时追加不同 plan，两条都保留；mock os.replace 抛错，旧记录仍可读；冲突不改旧正文 |
| 继承 | key 引用、只跟随一次；缺失/自引用/链式引用报错；有效 rank=0；显式 materialize 后与源独立 |
| 缺口 | 由 remember 的真实 body 读出 plan_id 与文本；删段落再覆盖后消失；长未解决段落不能绕过总预算 |
| UIA 授权 | 只读白名单在 allow_foreground=false 时可查询；写/未知成员拒绝且 provider 调用为零；不能按 Get 前缀放行、不能读取原始 Element/pattern/textRange 字段或执行表达式 |
| UIA 定位/诊断 | 根目标、唯一 AutomationId/name、重复/未命中/不完整树分别覆盖；诊断 warning 保留获取/遍历错误，吞错的 None 标 cause_unknown；大小写、数字 GetPattern 回退、SelectionPattern2 缺 constructor、无 getter、getter抛错均可解释 |
| UIA 返回值 | Value属性、DocumentRange.GetText、TextRange列表、Control列表、合法False查询、动作False；未知对象返回 result unsupported 且不重放；总字符/条目/深度预算与 API possibly_truncated 分开；4096上限返回4096单位也不得标全文 |
| UIA 线程/进程 | 至少一个实际 HTTP MCP 请求在 worker 主线程完成定位→pattern→调用→投影；父端无COM对象，初始化/退出配对；同步工具线程池不得绕过worker直调 |
| worker 生命周期 | 首次transport_ready/ready顺序与共用握手deadline；初始化失败不发送动作；busy不排队且not_started；执行超时/崩溃只失败一次，不重放，确认旧进程退出后可重建；transport未完成或进程未回收则sticky unavailable；stopping关闭不并发碰连接 |
| IPC/deadline | 假worker半个帧头/半个正文后停住、发送背压、EOF、错误request_id、坏JSON、超限长度均有界失败并回收；图片超限略图仍保留树；metadata超限不得截坏帧；重复超时不积累进程或应用收发线程 |
| 原有动作 | 原生匹配重名不发消息；命名目标缺失/模糊多义/树不完整时不激活、不动光标、不点窗口中心；空click无唯一原生目标返回target required；无效矩形拒绝；真实键鼠前可见/非最小化/焦点校验；快捷键规范化保留；已调用后的异常/False/不可读不悄悄换另一条写路径；Value=None与缺pattern不假报已验证或确定失败；滚动使用NoAmount与正确的上下枚举，False/位置不变可解释 |
| 启动归属 | 直接进程/已证实子孙的全新窗口才可隐藏；不相关窗口零隐藏/激活调用；baseline含隐藏窗口；单实例/broker/权限失败/PID或HWND复用不误认；原字段兼容，unknown/applied/partial报告与实际证据一致 |
| 消息校验/权限 | 无效/广播/本服务PID同步hwnd、bool/越界参数、错误控件类拒绝；未知标量要unsafe和前台授权；未托管COPYDATA/DROPFILES即使unsafe也拒绝，托管GET/SET走专门分支；异步查询拒绝 |
| 消息结果 | 异步成功仅queued无result；同步成功returned有指针宽有符号result；0/-1查询合法；API失败LastError=1460/其他/0可区分，不杜撰超时；超时execution_state=unknown且不重发；前台字段每个分支都存在 |
| 托管文本 | 中文/emoji/空串/NUL/孤立代理输入、容量边界、读回修复；GETTEXT空串与可能截断；SETTEXT错误返回、完整匹配/不符/验证不可读/预算耗尽；超过4096的长文本写入不得被预览截断误判失败；内部缓冲按UTF16单位分配，不读取超时残片，不将Static图像当文本 |
| GUI 回归 | 自建跨进程窗口上验证现有工具、同步文本/状态、ExpandCollapsePattern 等能力；检查实际效果、光标/前台；清理只触及本轮PID/HWND；不固定QQ节点数或延迟 |
| MCP/文档/skill | tools/list 共15项，7项新签名一致；真实请求的bool→int、字符串→授权等强制转换被拒绝；错误结构、权限docstring、独立skill模板和路线一致；未知版本观察可写而不能升级信任；skill包含原生/UIA/Electron/UWP/自绘/虚拟列表/外部接口及未试方向；历史数字不当新测结果 |
| 性能 | 同一窗口/任务核验常用七项探测未被改成全量探测；记录读树样本及环境，不能用历史 QQ 时延作硬阈值 |

真实 QQ/Electron 测试属于可选现场集成证据，不能成为所有安装环境的单元测试依赖。保存应用实际版本、exe 路径、启动 flags、前台/可见性、请求参数、计数口径、耗时和副作用，才可更新记忆中的实测结论。

## 9. 平台资料

以下官方文档用于约束接口，不替代现场 provider 的效果验证：

- [S1] Microsoft PostMessageW：异步语义、广播句柄、指针与跨进程消息限制。`https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-postmessagew`
- [S2] Microsoft IUIAutomationWindowPattern：Close / SetWindowVisualState 的窗口副作用。`https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nn-uiautomationclient-iuiautomationwindowpattern`
- [S3] Microsoft WM_LBUTTONDOWN：客户区坐标。`https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-lbuttondown`
- [S4] Microsoft WM_MOUSEWHEEL：屏幕坐标与滚动量。`https://learn.microsoft.com/en-us/windows/win32/inputdev/wm-mousewheel`
- [S5] Microsoft SendMessageTimeoutW：等待标志、返回值/输出结果、同输入队列与 timeout 边界。`https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendmessagetimeoutw`
- [S6] Microsoft WM_GETTEXT：缓冲区容量、文本长度与 Static 图像例外。`https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-gettext`
- [S7] Microsoft WM_SETTEXT：文本指针、标准控件的返回语义。`https://learn.microsoft.com/en-us/windows/win32/winmsg/wm-settext`
- [S8] Microsoft The Old New Thing：SendMessageTimeout 超时不等于取消处理，系统封送与目标侧缓冲寿命。`https://devblogs.microsoft.com/oldnewthing/20110915-00/?p=9643`
- [S9] Python socket：socketpair、nonblocking、send/recv 与 EOF。`https://docs.python.org/3.13/library/socket.html`
- [S10] Python select：Windows 的 socket 等待与剩余超时。`https://docs.python.org/3.13/library/select.html`
- [S11] CPython resource_sharer：Windows spawn 的 DupSocket 移交与缓存取走；实现依赖需随实际 Python 版本复核。`https://github.com/python/cpython/blob/v3.13.9/Lib/multiprocessing/resource_sharer.py`
- [S12] Microsoft Security Identifiers：capability SID 前缀 S-1-15-3，用于纠正历史 S-1-4-* 分类。`https://learn.microsoft.com/en-us/windows-server/identity/ad-ds/manage/understand-security-identifiers`
- [S13] Microsoft Process Handles and Identifiers：进程ID与句柄的生命周期。`https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers`
- [S14] Microsoft PROCESSENTRY32：父进程ID快照字段；结合进程创建时间核对归属，不能只凭PPID。`https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32`
- [S15] Pydantic Strict Types：严格的布尔、整数与字符串验证。`https://docs.pydantic.dev/latest/api/types/`

依赖内部 API 的来源为已安装 `windows-mcp 0.8.8` 的 `uia/controls.py`、`uia/enums.py`、`uia/patterns.py`；升级依赖时重新核验初始化器及 constructor 映射。原稿的 QQ 数值是缺少原始日志的历史观测，见设计稿证据表，不作固定验收值。
