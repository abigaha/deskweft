# DeskWeft 三层框架：实施交接

审核修订：2026-11-08。文件日期不表示功能已经完成。
状态：基础三层实现已落地；本文保留基线实施要求与历史证据，不推断原两文档的审批结果。本轮补齐结构化目标、后台只读属性、专用 find_items 枚举，以及具体候选路线和避免探索过早停止的 skill 规则；新增规则和验收分别标在 §4.3、§4.5.1、§4.7、§6.1、§7、§8。历史现场数据不作为本轮复测结果；本轮真实测试另见独立报告。
设计理由见 [three-layer-design-v2](2026-11-08-three-layer-design-v2.md)。**本文件是签名、字段、行为和验收的唯一契约。**

## 0. 实施者必须先读的目标

本框架有三个并列目标：**skill 提供足够广的探索思路，memory 清楚保存经验与不确定性，MCP 为这些思路提供可靠的执行与读回能力。** 优化围绕这三个目标展开，不能用删掉探索方向、忽略返回值或统一拒绝复杂操作来代替可靠实现。基础轮原定 7 个新增工具全部保留，不采纳“先删去通用出口和审核工具”的缩减建议；本轮另补专用 find_items，解决 ItemContainer 的 NULL/引用参数断路。

交接对象可能不具备设计者的推理能力。实现时必须逐项落实本文的路径、签名、字段、分支、错误及测试，不依赖历史对话；不能把“接口已注册”“API 没抛错”“消息已入队”当成任务成功。下文代码块中用 `...` 表示签名的部分不是实现，具体算法由其后的规则限定；缺少平台能力时必须报告具体缺口，不能编造成功。

历史实测与未试方向的完整资料在设计稿 §7，各项数字保留原口径并注明缺失的环境证据。它们是实施与复测输入，不能在再次精简时删除。

### 0.1 DeskWeft 改名与迁移边界

项目现名为**DeskWeft**，Python包、CLI和客户端注册名为`deskweft`，新安装目录为`%LOCALAPPDATA%\deskweft`，任务名为`deskweft-helper`。MCP的16项工具、端口8765和skill目录名`windows-app-automation`保持原契约。迁移时核对并替换旧`winmcp-helper`任务与客户端注册，避免两个服务同时执行或写同一memory根目录。

记忆路径按`DESKWEFT_MEMORY_DIR`→`WINMCP_MEMORY_DIR`→`%LOCALAPPDATA%\winmcp\memory`解析，旧默认目录是数据兼容路径；本次不迁移、合并或重写记忆。旧记录中的产品名、实测、plan_id、revision与审核状态保留。

两份live报告中的`winmcp`路径、模块、desktop名称和源码哈希是改名前原始证据，继续按原口径保存。改名后的纯命名变更须由新离线回归和部署验收覆盖；不得仅改报告命令或哈希就声称GUI任务已重新验证。改名后的实际离线、部署和客户端配置验收记录如下，范围不扩展为GUI复测。

改名验收（2026-11-08）：`uv build`生成`deskweft-0.1.0`的sdist/wheel成功；新`%LOCALAPPDATA%\deskweft\.venv`按旧环境86条constraints安装87包，项目名替换但依赖版本未升级。新venv执行`-X utf8 -B -m unittest discover -s tests -q`实得357项、14.487秒、OK；另以`-I`隔离源码路径，确认导入真实wheel的`site-packages/deskweft`，CLI entry point为`deskweft.server:main`。skill的quick_validate和4份PowerShell脚本的语法解析另实得通过。分发以完整GitHub仓库为准，wheel仅用于MCP模块/entry point验证，本次不发布PyPI。

实际部署已启动`deskweft-helper`，8765仅有一个127.0.0.1监听，owning PID命令行属于新venv的`-m deskweft.server`。首次固定等待6秒曾误报失败，服务实际约8秒后就绪；改为30秒有界轮询及监听归属核对后，已重启真实验证成功。旧`winmcp-helper`的XML在本机备份后已正式移除，仅保留新任务；旧数据根目录未删除。

重启前后两次真实HTTP probe均取得`server_info.name=deskweft`及16项工具（含`find_items`）；`see(hwnd=0)`首块文本一次JSON解码为dict，返回invalid arguments、detail为hwnd、execution_state=not_started、foreground_changed=false。这覆盖真实服务握手、工具发现和进入provider前的拒绝分支，不是应用GUI动作成功链。三条QQ plan的revision、rank=0、reviewed=false、proven=false均与改名前相同，全部memory文件的前后SHA256保持一致；没有重写记忆来适配新名称。

卸载脚本另以隔离fake配置验证Claude独立清理及首行TOML处理等4例，全部通过；没有真实卸载服务。GUI自检、QQ/微信和ItemContainer任务均未因本次改名重跑，原报告的命令、成本、效果与旧哈希继续保留。

客户端同步实际修改4份client/workspace配置，三份完整skill各含入口、reference与两份helper，全部4文件SHA256逐一等于源码；只读幂等`--check`为0 pending、synchronized=true，其余解析后配置结构、URL和timeout保留。Codex CLI读到新`deskweft`注册及原60/300秒设置；Claude CLI返回User config/Connected及正确HTTP地址；DSH patch/workspace的新id、serverName、path和title通过结构校验。配置备份留在本机忽略目录。当前Codex/DSH进程未重启，既有会话仍需重载后工具前缀才更新，不将配置已同步写成所有运行中会话已热重载。

GitHub原仓库ID1448032729保留，已改名为`abigaha/deskweft`（public/master），`origin`已更新为`https://github.com/abigaha/deskweft.git`。

改名后skill交付文件的SHA256如下（路径相对`skills/windows-app-automation`）；这些新哈希不替换live报告中改名前源码的实测哈希。

| 文件 | 改名后SHA256 |
|---|---|
| SKILL.md | `513dd2ee04b82a942dae3236ce54a9f9d9072bf2d36d69b53b7cad6dab44d836` |
| references/foreground-protection.md | `8831efd682f74cad02fd149b433449ddb2bb4c6cb8a24bf1aa706a96addb2fcc` |
| scripts/qq_private_probe.py | `32cdf974354f256952bead1489df9796bd8d212c559fef5f818208729b6576c2` |
| scripts/private_desktop.py | `14bae0a5c2fdbcd247b8f2956dd27b18d311374bde01a8ecf973be6cea3e5d96` |

## 1. 范围与基线

基线提交：`abb55bd`；实施前重新检查 `git status` 和实际导入路径，不依赖固定行号或机器上的旧副本。

- 保留现有 8 个 MCP 工具：`open_app`、`reveal`、`windows`、`see`、`click`、`type_text`、`key`、`scroll`；本轮仅兼容扩展 click/type_text/scroll 的 target 类型，原字符串、其他参数与默认值保持。
- 基础轮新增 **7 个** MCP 工具：`app_info`、`invoke_pattern`、`post_message`、`recall`、`remember`、`approve`、`confirm_proven`，与原 8 个合计 15 个；本轮新增 `find_items` 后当前共 **16 个**。
- 新增 `skills/windows-app-automation/SKILL.md`。不做插件、数据库、自动计数、跨机同步或记忆浏览 UI。
- 本轮只支持一个服务进程写一个 memory 根目录；同进程的并发 MCP 会话必须安全。人工编辑前先停止服务。

### 1.1 修改落点

| 路径 | 修改内容与相关调用方 |
|---|---|
| `deskweft/memory.py`（新） | 单文件记录、匹配、排序、继承、写入和审核；由 server 包装调用 |
| `deskweft/appinfo.py`（新） | hwnd → pid → exe → 版本证据；复用 win32 的窗口元数据 |
| `deskweft/tree.py` | 扩展 `pattern` / `patterns`，增加 `pattern_detailed` / `read_detailed` 诊断入口和 `native_hwnd`；调用方为 `describe`、`act`、`check`；保留现有签名 |
| `deskweft/act.py` | 新增独立 `invoke_pattern`，复用 `_done`；增加有界结果投影；修正目标歧义和未命中时点窗口中心的分支，不把新参数塞进现有 `act()` |
| `deskweft/items.py`（本轮新） | 专用 `find_items`，同 worker 调用内处理 ItemContainer 的 NULL 起点、COM 续项、循环检测、匹配序列分页及有界元数据；不开放任意 Control 输入 |
| `deskweft/launch.py` | 两段隐藏/回交前台循环共用进程归属判断，只作用于已确认的启动目标；无法确认单实例/broker窗口时如实报告 |
| `deskweft/uia_worker.py`（新） | 单个可回收 UIA 子进程、串行调度、超时与初始化；不把 COM 对象交给 HTTP 线程 |
| `deskweft/win32.py` | 新增 `post_message`；同步用 SendMessageTimeoutW、异步用 PostMessageW，服务端托管受支持的文本缓冲区 |
| `deskweft/server.py` | 基础 7 个加 find_items 工具包装；UIA 请求交给 worker；修正 INSTRUCTIONS 与真实路由不符的描述 |
| `pyproject.toml` | 显式增加 `PyYAML>=6,<7`；其余新增功能用标准库与已有 UIA 依赖 |
| `tests/test_memory.py`、`tests/test_tools.py`、`tests/test_uia_worker.py`（新） | 临时目录、假 provider 和假 worker 的行为测试，无需真实 QQ |
| `tests/test_items.py`、`tests/live_itemcontainer.py`、`tests/live_explorer_items.py`（本轮新） | 有界参数/分页/结果/失败测试；显式真实 MCP→worker→COM 的 WPF 与 Explorer 验证，live 脚本不随 unittest 自动运行 |
| `tests/fixtures/itemcontainer.ps1`、`tests/fixtures/explorer_items.ps1`（本轮新） | 独立合成数据、归属与关闭入口；Explorer 提供 Open/Reveal/Close，后两者复核精确 HWND/folder |
| `docs/reports/2026-11-08-itemcontainer-live.md`（本轮新） | 本轮环境、请求、真实 provider 结果、失败假设、原始记录摘要及证据边界，与历史测量分开 |
| `tests/test_see_transport.py`（本轮新） | 真实FastMCP序列化验证有图/无图/worker错误/非法结果四条see返回分支，mock桌面执行，不冒称真实GUI验证 |
| `docs/reports/2026-11-08-qq-wechat-live.md`（本轮新） | QQ/微信当前环境、完整闭环成本、真实抢焦/失败保护证据、MCP与独立COM边界及未完成方向，隐去个人/聊天内容 |
| `deskweft/check.py` | 已按本次PID/HWND核对归属后清理；自建窗口和应用的GUI效果仍须现场验收 |
| `README.md`、`skills/windows-app-automation/SKILL.md` | 工具清单、权限和探索流程，与本契约一致 |
| `skills/windows-app-automation/references/foreground-protection.md`（本轮新） | 调用前保护的可核验范围、失败历史、随包脚本操作步骤、异常清理与证据边界；不将开关或端点观察当阻止能力 |
| `skills/windows-app-automation/scripts/private_desktop.py`、`qq_private_probe.py`（本轮新） | 随skill提供的私有desktop/Job控制器与QQ身份/搜索runner，独立CLI而非新增MCP工具；真实dispatch线程核验、原状态恢复和Job活动归零分别负责 |
| `tests/test_private_desktop.py`、`tests/test_private_qq_probe.py`（本轮新） | 隔离控制器生命周期与runner定位、日志、结果未知/恢复边界的离线回归；实际GUI/provider另存本轮报告 |

本轮修补的修改面是 `tree.py` 的共享 `target_error` 校验、完整树定位及字段读取诊断，`act.py` 的四个 target 调用方与只读成员表，`items.py` 的专用容器查询，`server.py` 的严格 schema 和工具说明，以及相关测试、README、两份规格、报告和 skill。`uia_worker.py` 保持普通 JSON 帧协议，固定分派增加 find_items；测试证明 selector dict 原样传递，不新增 COM 缓存或另一套定位规则。memory 格式、信任位、基础七个新增入口、广软件探索范围和历史失败证据继续保留。

### 1.2 可复用入口及限制

`win32.title/class_name/foreground/list_windows/children`、`tree.read/find/pattern`、`launch.force_foreground/is_shown`、`act._done` 均已存在。

必须按实际代码理解这些入口：

- 当前 `act()` 在尝试 Legacy 路由**之前**检查 `allow_foreground`。默认 `click()` 只尝试原生控件消息，不能宣称默认执行后台 Legacy 点击。
- 当前 `tree.pattern()` 只找具名 getter；`patterns()` 只探测 7 项并返回小写，不是完整能力清单。
- 基线 `tree.read()` 曾过滤无名字、无七项已知 pattern 的容器。本轮完整定位必须保留全部可读、非 offscreen 节点，匿名节点仍可能匹配 control_type/native_hwnd/rect；七项 pattern 摘要不是候选过滤器。offscreen 过滤及其数量继续报告，空结果仍不能证明应用没有 UIA。
- 读树时间预算只在 Python 遍历间隙检查，不能中断一次阻塞的 provider/COM 调用。不要承诺硬超时。

### 1.3 共同返回约定

所有进入函数的新增工具调用成功包含 `ok: true`；业务失败包含 `ok: false, reason: str, detail: str`，可选 `hint`、`needs_permission`。`recall` 没找到是成功。尚未进入函数的 schema/协议错误由 FastMCP 返回标准参数错误，不伪造成 provider 故障；验收要证明工具函数未执行。

通过参数解析并进入窗口工具的请求，无论成功、拒绝还是抛错，都补上：

```python
{"foreground_before": before, "foreground_after": after,
 "foreground_changed": before != after}
```

`foreground_changed` 只是调用前后两个采样点的观测，不能证明中途没抢焦点，也不能替代事前授权。UIA 执行成功和消息入队均不等于业务目标已完成；调用方必须验证效果。

窗口动作若已由 worker 提供真实 `foreground_before/after/changed`，server 必须原样保留，不能在动作结束后重新取两次样覆盖它们。worker 没有返回采样的失败路径，由 server 在整个 worker 调用之前、之后各取一次再补齐；不得只在完成后采样。前台观察是权限与证据的一部分，不能让包装层把一次真实变化改成 false。

本文 int/bool/str 表示严格 JSON 类型，不接受 true 当1、字符串"true"当授权或数字转成字符串。FastMCP 的包装层使用已有 Pydantic 的 `StrictInt/StrictBool/StrictStr` 或等价 strict 注解，nullable version 用 `StrictStr | None`；参数名、默认值与 JSON 工具类型保持本文签名。[S15] 仅在函数内部做 isinstance 校验不足以防止框架先强制转换；HTTP/MCP 测试必须用真实 bool/字符串错类型确认拒绝。内部函数仍校验，不能只依赖包装层。

## 2. memory.py：唯一存储格式

### 2.1 根目录与文件名

```python
from hashlib import sha256
from pathlib import Path
import os

def memory_root() -> Path:
    configured = (os.environ.get("DESKWEFT_MEMORY_DIR")
                  or os.environ.get("WINMCP_MEMORY_DIR"))
    return (Path(configured).expanduser() if configured else
            Path(os.environ["LOCALAPPDATA"]) / "winmcp" / "memory")  # 保留历史数据目录

def make_key(app: str, version: str | None) -> str:
    tag = "unversioned" if version is None else version.strip()
    return app.strip().casefold() + "@" + tag

def record_path(root: Path, key: str) -> Path:
    return root / "playbooks" / (sha256(key.encode("utf-8")).hexdigest() + ".md")
```

根目录优先使用`DESKWEFT_MEMORY_DIR`，其次兼容`WINMCP_MEMORY_DIR`，都未设置时继续使用`%LOCALAPPDATA%\winmcp\memory`。改名不迁移或重写既有记录，不改plan_id、正文、revision及信任位；不同时启动旧新服务写同一根目录。

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
verified_with: deskweft 0.1.0
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

def forget(app: str, version: str | None, plan_id: str = "",
           expected_revision: str = "", confirm: bool = False) -> dict: ...

def unresolved() -> list[dict]: ...
```

`unresolved()` 仅为内部函数，不额外暴露 MCP 工具。测试通过 patch `memory_root()` 使用临时目录，不能改真实用户记忆。

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

### 2.6.1 删除过时方案

记忆的用途是让下一次少走弯路，因此**过时信息必须可删**：留着它，`recall` 会把旧结论
当成当前事实交给调用方，比没有记录更糟。与之相对，失败路径和未试方向属于证据，不删。

- `forget(app, version, plan_id, expected_revision)` 删除一条方案：`plan_id` 与
  `expected_revision` 均必填，在同一写锁内比较 revision，不一致返回 `stale plan` 且不改文件
  ——与审核同一条规则，删除的是调用方看到的内容，不是后来替换掉的内容。
- 删除后若 `plans` 为空，连记录文件一起删除，不留下 `recall` 仍会列出的空壳。
- `plan_id` 为空表示删除整条记录，必须 `confirm=true`；缺省返回
  `confirmation required`，不写盘。
- 继承记录（`see`）不能删除：它是指针，内容在源记录里；返回 `inherited record`。
  删除源记录不影响已指向它的其他 key，也不做级联。
- 只影响目标 key：其他版本、其他应用、同名 key 的其他方案不动。损坏记录返回
  `invalid record` 并保留原文件，不能靠删除跳过解析错误。
- 写盘失败保留旧记录；删到空时的文件删除失败返回 `write failed`。
- 成功返回 `{ok: true, key, removed: [id...], record_removed: bool}`。
- 删除不可逆，且不进入 `## 更新记录`：需要保留"某结论被证伪"的说明时，先改正文再决定
  是否删除该方案，不要用删除代替更正。

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
要完成的任务、当前项/可见页/全量范围、授权的副作用和成本要求，
以及什么可观测结果与完整性证据才算完成。
## 环境与适用条件
记录时间、app/版本及来源、exe、启动参数、窗口可见/前后台状态、
DeskWeft/依赖版本；原记录缺失的字段写“未记录”，不能补猜。
## 已验证步骤
逐步列工具、实际参数、返回值、效果验证与前台/光标副作用；
只在该环境验证过的步骤才能放这里。
## 已尝试但失败
列尝试、具体输入、观测或错误、当时环境、失败范围与下一步。
“这个版本此窗口未生效”不能改写成“这个 API 对所有应用无效”。
## 实测记录
原始计数/耗时/像素变化及统计口径、样本、日志或截图位置；
候选路线台账包含基线、适用依据、状态、任务覆盖、定位+调用+验证全链路成本、
工具/全树读取次数与前台/鼠标证据；未测项写未测，rank 不代替效率。
历史转录值和本次新测值分开，冲突数据并列，不能挑一个覆盖另一个。
## 未解决
缺什么能力、影响哪个目标、已试到哪里、下一步需要哪个接口。
## 未试方向
每项写“未验证”、思路依据、对照步骤、预期观测、代价和回退方式；
权限未满足与工具尚未实现分别标注，不得记成已试失败。
说明本次未试或停止的可核实原因；一个方向受阻不抹去其他适用候选。
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

## 3. appinfo.py：证据链取版本，逐级兜底

版本来源不是单一途径加一条兜底，而是**一条有优先级的证据链**：每一级都标明它能证明什么、不能证明什么，取到就停，同时在返回值里如实报告用了哪一级。

### 3.0 为什么必须多级（实测对照，2026-11-08）

同一套探测方法在 QQ 和 Edge 上得到完全不同的结果：

| 来源 | QQ | Edge |
|---|---|---|
| 1 exe 路径里的 `versions/` 段 | `None` | `None` |
| 2 子进程命令行 `--app-path` | **`9.9.22`** | `None` |
| 3 唯一候选目录 | `9.9.22-40824` | 无目录 |
| 4 `versions/` 候选列表 | `['9.9.22-40824']` | `[]` |
| 5 `FileVersion` | `9.9.19.35469`（**落后**） | `157.0.4341.42`（**正确**） |
| 6 `ProductVersion` | `9.9.19.35469-12e4987f` | `157.0.4341.42` |
| 7 同级数字目录 | `None` | `157.0.4341.42` |

**结论：没有哪一级能覆盖所有应用。** QQ 只有 2/3 得到真实构建，Edge 只有 5/6/7。任何单级实现的方案都会在其中一类应用上返回 `None`。

### 3.1 接口

```python
def app_info(hwnd: int) -> dict: ...
def _process_path(pid: int) -> str | None: ...
def _file_version_info(exe: str) -> dict: ...
def _version_evidence(pid: int, exe: str | None,
                      info: dict) -> tuple[str | None, str, list[str]]: ...
```

`_version_evidence` 返回 `(version, source, warnings)`。`source` 取值固定：

| source | 含义 | 可信度 |
|---|---|---|
| `path_segment` | exe 路径本身含活动构建目录 | 最高：直接证明 |
| `child_cmdline` | 子进程命令行指向构建目录 | 高：启动器结构下间接证明 |
| `sole_candidate` | 唯一候选目录，无其他解释 | 中：推断，须附 warning |
| `file_version` | 文件资源版本 | 中：可能落后于实际构建 |
| `sibling_dir` | 同级数字目录 | 低：启发式 |
| `None` | 无证据 | — |

### 3.2 取版本顺序（逐级，取到即停）

```
1. path_segment
   exe 路径匹配 [\\/]versions[\\/](\d+(?:\.\d+)+(?:-\d+)?)
   → 取 "-" 前完整版本。QQ/Edge 都不命中，但这是唯一直接证明的方式。

2. child_cmdline
   用 psutil 枚举同 pid 的直接子进程，读命令行（§3.3 已实测可行，非管理员亦可），
   匹配同样的 versions/ 模式。
   → QQ 命中 9.9.22。实测 5 个子进程同时给出该值。

3. sole_candidate
   枚举 os.path.dirname(exe)/versions/ 下的目录，
   名必须完整匹配 \d+(?:\.\d+)+(?:-\d+)?（注意：必须保留 -(build) 后缀，
    只写 \d+(?:\.\d+)+ 会漏掉 9.9.22-40824，见 §3.4）。
   恰好一个候选才采用，并写 warning "inferred from sole candidate, not verified"。
   零个或多个 → 跳过，禁止猜。

4. file_version
   version.dll: GetFileVersionInfoSizeW → GetFileVersionInfoW → VerQueryValueW。
   取 VS_FIXEDFILEINFO 的完整四段。绝不截前两段（9.9.19.35469 截成 9.9 是错的）。
   → Edge 命中 157.0.4341.42。

5. sibling_dir
   os.path.dirname(exe) 下是否有形如纯版本号的目录（Edge 的 Application/157.0.4341.42）。
   命中则记 source="sibling_dir" + warning。

6. 全部失败 → version=None, source=None。
   由调用方走 remember(..., version=None) 记成 app@unversioned 观察。
```

### 3.3 读子进程命令行：用 psutil，不需要 PEB

跨进程读 `PEB` 需要 `NtQueryInformationProcess` + `ReadProcessMemory`。**实测不需要**：`psutil` 在**非管理员**下就能读到子进程命令行。

实测结果（QQ 主进程 pid 15168，未提权）：

```
children:
  pid 26212  type=?         version=9.9.22-40824   ← 命中
  pid 14436  type=renderer  version=9.9.22-40824   ← 命中
  pid 19684  type=gpu-process  version=-
  pid 19556  type=utility      version=-
  ...
```

实现：

```python
import psutil

_VER = re.compile(r"[\\/]versions[\\/](\d+(?:\.\d+)+(?:-\d+)?)", re.I)

def _child_version(pid: int) -> str | None:
    try:
        proc = psutil.Process(pid)
        children = proc.children(recursive=False)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None
    for child in children:
        try:
            for arg in child.cmdline():
                m = _VER.search(arg)
                if m:
                    return m.group(1).split("-")[0]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None
```

要点：

- `psutil` 已在 venv（7.2.2），不引入新依赖
- 只查**直接子进程**（`recursive=False`），够用且快
- 单个子进程读失败就跳过，不整体失败
- 命中的通常是 `--app-path=...` 那个参数，也可能是别的位置，所以对**每个参数**都匹配一次

只有当 `psutil` 路径也失败时，才降级到第 3 级（sole_candidate）。

### 3.4 两个已实测的陷阱

**正则必须保留 `-(build)` 后缀。**

```
VER_EXACT = re.compile(r"\d+(?:\.\d+)+(?:-\d+)?")   # 对
VER_SHORT = re.compile(r"\d+(?:\.\d+)+")            # 错，漏掉 9.9.22-40824
```

用错的后果：候选列表永远为空，第 3 级永远不命中。（这个错本次实测时自己踩过一次。）

**`versions/` 目录里混有非版本文件。** 实测有 `channel.json`、`config.json`、`setting.json`。必须 `os.path.isdir()` + 完整正则双重过滤，否则会把 `setting.json` 当候选。

### 3.5 返回字段

```python
{"ok": True, "hwnd": hwnd, "pid": pid, "name": Path(exe).stem,
 "exe": exe, "version": version, "source": source,
 "file_version": file_version, "product": product, "company": company,
 "version_candidates": candidates, "warnings": []}
```

- `version_candidates` 永远返回（诊断用），**但不参与 version 决策**，除非走第 3 级
- `warnings` 记录降级原因，例如 `"sole candidate, not verified"`、`"cmdline unreadable: AccessDenied"`
- 进程已退出或无权读 exe → 结构化错误；exe 可读但无版本 → 仍成功（`version=None`）

### 3.6 skill 如何使用 source

不要只给 agent 一个版本号，要让它知道可信度：

| source | skill 的行为 |
|---|---|
| `path_segment` / `child_cmdline` | 直接 `recall("name@version")`，当作确定版本 |
| `sole_candidate` | 用它查，但未命中时也要试 `recall("name")` 家族 |
| `file_version` / `sibling_dir` | 先 `recall("name@version")`，未命中再 `recall("name")`；记录时写清 source |
| `None` | 只用 `recall("name")`，新观测存 `app@unversioned` |

## 4. UIA：线程、pattern 与权限

### 4.1 在可回收的工作进程内完成桌面调用

本机已安装的 `windows-mcp 0.8.8` 提供：

```python
from windows_mcp.uia import UIAutomationInitializerInThread
```

新增 `deskweft/uia_worker.py`，为会进入 UIA 的 `see/click/type_text/key/scroll/invoke_pattern/find_items` 提供一个复用的工作进程。它也包住这些路径内的 PrintWindow 和既有同步窗口消息，避免截图或原生动作阻塞 HTTP 线程。工作进程用 `multiprocessing.get_context("spawn")` 创建，不依赖父线程的 COM 状态。

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
3. action 分发表只包含 `see/click/type_text/key/scroll/invoke_pattern/find_items`，不接收 Python 路径、eval 或用户指定的函数。执行函数和返回值转换在同一个 worker 主线程完成。
4. `see` 在 worker 中完成截图与可选 UIA 读取；worker 内部与父端解码后的结果使用 `{meta: dict, png: bytes | None}`，JSON 线上把 png 转成 `png_b64`；server 再按现有约定组装文本和 Image。`meta.elements` 在 worker 内剔除 `_el`，不能先把对象传回父进程再剔除。
5. `see(with_tree=true)` 同时补充 `native_children`，复用 `win32.children(hwnd)`，返回其已有的 hwnd/class/text/rect 普通字段，最多 `max_elements` 项，并带 `native_children_truncated`。即使 UIA 为空也提供原生子控件；消息工具由此得到具体 child HWND，不能要求 agent 猜句柄。
6. `see` 的 worker 总预算取 `max(3000, timeout_ms+1000)` ms，允许截图及转换开销，公开 `timeout_ms` 仍是树遍历预算。现有四动作总预算 8000ms；新增 invoke 的总预算由 §4.3 定义。超时边界包含分派后的执行、转换与回包，启动 ready 的时间单独报告为 `startup_ms`。
7. 父进程用下方**非阻塞 socket 帧协议**，发送、接收帧头、接收正文都受同一个单调时钟 deadline 约束。不能用 `Pipe.poll(timeout)` 后直接 `recv()`：半帧可让 recv 再次无界阻塞，send 也有同样问题。不得只给 Future 加 timeout、每次另起收发线程或任由旧调用后台继续。超过预算时 terminate **自己创建的 worker**，join 最多 1000ms，必要时 kill 后再 join 1000ms，finally 关闭 socket 和已退出 Process 的句柄；这些清理时间在执行预算之外单独报告为 `cleanup_ms`。若仍无法回收，标记 `worker unavailable`，禁止另起无限多个 worker。
8. 超时/子进程崩溃时该次请求只返回一次失败，字段见下文；后续调用可建立新 worker，但**不自动重放上一条请求**。正常退出通过 close 通知 worker、结束其上下文、join，再关闭句柄。
9. 普通 Python 异常在 worker 转为结构化错误后可继续服务；进程退出、连接断开、request_id 不符则丢弃该 worker。用 finally 释放父调度锁，避免一次错误让全部后续调用永远 busy。

不要缓存到父进程、跨线程传递或返回 `_el`、Control、Pattern 等 COM 对象。`server.py` 的同步 MCP 包装只传普通参数给 `uia_worker.call`，不能再在 HTTP 线程直接调用 UIA；公开工具的其他参数与原生优先顺序保持，target 的兼容扩展以 §4.5.1 为准；§4.5 的定位拒绝与效果报告必须修正。direct-call 单元测试自行进入 UIA 上下文，真实 MCP 测试必须经过 worker。

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
    from . import act, items, tree
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
        "find_items": items.find_items,
    }
```

`_see(hwnd, with_tree=False, timeout_ms=1500, max_elements=200)` 在父端发送前及 worker 入口都验证：hwnd 为合法正整数且不是 bool，with_tree 为真正 bool，timeout_ms 为 1–30000 的整数，max_elements 为 1–10000 的整数，均排除 bool。拒绝负数，不能让 `children[:-1]` 泄出几乎全量列表。采集顺序：验证 `IsWindow(hwnd)` → 构造 ok/hwnd/title/class → `win32.grab` → None 写 image_unavailable，否则保留 png/尺寸 → with_tree 时 `tree.read_detailed`、剔除 `_el`、补诊断与 native_children → 返回 `{meta, png}`。不能以标题为空判断不存在；合法无标题 child 窗口也需要可读。`native_children` 取现有 `win32.children` 全量枚举后前 max_elements 项，枚举也在 worker 预算之内。`tree.describe` 增加 `native_hwnd`：读取 `int(el.NativeWindowHandle or 0)`，异常回 None 并记 warning，不用 AutomationId 冒充 HWND。

`_worker_main(channel)` 的完整控制流：

1. `channel.setblocking(False)`，先发送 `{transport_ready:true}`，进入 `UIAutomationInitializerInThread()` 并成功执行 `_make_dispatch()`；异常时尝试发送 `{ready:false, detail:<异常类型与消息>}` 后退出，全部成功才发送 `{ready:true}`。两个启动消息由父端在 start 返回后的同一个 5000ms deadline 内顺序接收，不各给 5000ms。
2. 循环 `_recv_frame(channel, None)`；worker 空闲时允许阻塞等待，父进程始终负责本次 deadline。收到 close 退出上下文；收到其他 action 先核对固定表、整数 request_id 和 dict parameters，不合法则回 not_started 的结构化错误。
3. 调 `dispatch[action](**parameters)`；捕获普通异常，返回 `{ok:false, reason:"worker action failed", detail, execution_state:"unknown", retry_safe:false}`，不换路线、不重放。业务函数返回的具体拒绝/provider 错误原样保留。
4. action 为 see 且拿到 `{meta,png}` 时，检查图片大小，再转为 `{meta,png_b64}`；其余 action 只能含 JSON 普通数据。构造 `{request_id, result}` 并先 `_encode_frame`，编码/大小异常用一个短错误帧报告 `worker response too large` 或 `worker result invalid`，附 `call_completed=true, execution_state="completed", effect_verified=false, retry_safe=false`，绝不重做动作。
5. 用 `_send_bytes(channel, encoded, None)` 发送；连接错误或部分发送后失败直接退出，不在旧半帧后拼另一个错误帧。父端超时会杀死该 worker，即使 worker 正在 send 也能回收。EOF/非法帧退出；finally 关闭 child socket 并释放 UIA 上下文。

父端给 see 成功载荷补前台字段、start_ms/startup_ms/cleanup_ms 时合并进 **meta**，不能补在外层后被包装丢掉；see 失败与其他动作则直接补到结果 dict。已有 worker 前台字段必须保留，缺失时才用整个 worker 调用前后采样补齐，不能用动作后的两次采样覆盖。server 对 see 成功结果先构造显式 `TextContent(type="text", text=json.dumps(meta, ensure_ascii=False))`，有png才追加 `Image(data=png, format="png")`；无图时仍为单一metadata文本块，客户端一次JSON解码得对象，不能因FastMCP将普通文本列表再次序列化而变成数组/嵌套字符串。worker错误和非法worker结果也用单一显式TextContent表示错误对象，保留执行状态/诊断/前台字段，不将错误字典误当作Image。四分支须经真实FastMCP客户端验证；mock桌面执行的协议测试与真实GUI测试分别记证。其余六个包装原样返回结果。所有包装和docstring同时更新，不留下HTTP线程直调旧act.act的旁路。

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

root 获取异常、GetChildren 异常、AutomationId/Name/IsOffscreen 无法读取都会影响定位完整性，设 identity_complete=false；warning 至少含 stage、异常类型、消息、已知的节点标识/深度，最多 50 条，之后置 warnings_truncated。根返回 None 记录 root_status=absent，但原因仍可能未知，不解释成“应用没有 UIA”。矩形/可选 pattern 失败记 warning；不能因为一个可选 pattern 不存在就断言整个身份遍历不完整。**本轮修补保留全部可读、非 offscreen 节点，匿名且七项 pattern 摘要为空也不能删掉。**`filtered_anonymous` 字段为兼容保留且恒为 0；offscreen 过滤继续记录 `filtered_offscreen`。否则 name/id 为空的同类控件会被漏掉，造成 control_type/native_hwnd/rect selector 的虚假唯一。当前可见暴露树仍不代表虚拟列表全部数据。

把 `describe` 的取值拆到内部 `_describe(el, nth, diagnostics)`，公开 `describe(el,nth)` 调同一实现；让 read_detailed 能接收错误上下文，不复制另一套取值逻辑。`see` 原有 elements/timed_out 字段保留，并追加 limit_reached、identity_complete、tree_diagnostics。定位动作使用 detailed 结果，任何 timed_out/limit_reached/identity_complete=false 均在执行前拒绝 `tree incomplete`。

本轮保留更多匿名/空容器后，同一 max_elements 可能更早触顶；仍须拒绝不完整树中的表面唯一结果，不删除候选来迁就旧计数，也不宣称 selector 自动减少遍历或提速。成本变化用同任务、同预算的实际样本记录。

### 4.3 通用属性与方法入口

```python
def invoke_pattern(hwnd: int, pattern: str, target: str | dict,
                   method: str, args: list | None = None,
                   allow_foreground: bool = False,
                   timeout_ms: int = 8000) -> dict: ...
```

`server.py` 暴露完全相同签名。不要加进 `act()` 的 action 分支，不用 `text` 兼作方法名，也不猜默认方法。

- 校验合法 hwnd；`pattern/method` 非空；`timeout_ms` 是 1–30000 的整数且不是 bool，作为整个 worker 请求预算。args 列表项仅接受 str/bool/int/有限 float（数值排除 NaN/Infinity），不接收 null、对象、指针或表达式。顶层 args=None 仍按省略列表处理，不代表列表中可传 None。
- method 可为一个公共属性/方法名，或公共属性链，如 `Value`、`GetSelection`、`DocumentRange.GetText`。逐段按标识符校验，拒绝 `_` 开头、下标、括号、表达式；不能使用 eval。
- 用下方明确的只读成员表允许后台查询；表外成员按可能有副作用处理，`allow_foreground=false` 时在进入 provider 前返回 `needs_permission=true`。该参数只允许潜在副作用，不要求服务主动激活；不能按 Get 前缀猜安全，也不限制已授权调用的其他公开 wrapper 成员。
- `target=""` 明确表示根窗口，直接 `ControlFromHandle(hwnd)`；该参数仍需显式传入，空对象不能代替根目标。非空字符串在同一已初始化线程中调用 `tree.read_detailed(hwnd, timeout_ms=3000, max_elements=600)`，用 AutomationId 精确匹配优先、再用 name 精确匹配。对象 target 依 §4.5.1 对全部给定字段 AND 精确匹配，不套用字符串的优先级。
- `timed_out=true`、`limit_reached=true` 或 `identity_complete=false` 均返回 `tree incomplete`，即使部分结果中已命中也不动作。完整性以实际遍历/截断标志判定，数目本身不替代标志；恰好 600 个元素且遍历真正完成时仍可完整。完整读取后候选超过一个返回 `ambiguous target`，无候选返回 `no such control`；不得沿用 `tree.find()` 的首个模糊匹配执行任意方法。
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
    "AnnotationPattern": {"AnnotationTypeId", "AnnotationTypeName", "Author", "DateTime"},
    "DockPattern": {"DockPosition"},
    "DragPattern": {"DropEffect", "IsGrabbed"},
    "DropTargetPattern": {"DropTargetEffect"},
    "ExpandCollapsePattern": {"ExpandCollapseState"},
    "GridItemPattern": {"Column", "ColumnSpan", "Row", "RowSpan"},
    "GridPattern": {"ColumnCount", "RowCount"},
    "LegacyIAccessiblePattern": {"ChildId", "DefaultAction", "Description", "Help",
                                 "KeyboardShortcut", "Name", "Role", "State", "Value",
                                 "GetSelection"},
    "MultipleViewPattern": {"CurrentView"},
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
    "SpreadsheetItemPattern": {"Formula"},
    "StylesPattern": {"ExtendedProperties", "FillColor", "FillPatternColor", "Shape",
                      "StyleId", "StyleName"},
    "TablePattern": {"RowOrColumnMajor"},
    "TogglePattern": {"ToggleState"},
    "TransformPattern": {"CanMove", "CanResize", "CanRotate"},
    "TransformPattern2": {"CanZoom", "ZoomLevel", "ZoomMaximum", "ZoomMinimum"},
    "WindowPattern": {"CanMaximize", "CanMinimize", "IsModal", "IsTopmost",
                      "WindowInteractionState", "WindowVisualState"},
}
```

本轮表格与仓库 `act._READ_ONLY_MEMBERS` 逐项同步，依据已安装 windows-mcp 0.8.8 的实际 wrapper scalar getter 和既有结果投影维护；这不是任意 getter 自动放行。Legacy 的 `Name`、`Description`、`Value` 和 Window 的 `WindowVisualState` 现在允许后台读，`DoDefaultAction`、`Select`、`SetValue`、`SetWindowVisualState`、未知成员及未列出的 `Get...` 仍在 provider 前走权限门。`LegacyIAccessiblePattern.GetSelection` 的控件列表沿用 §4.4 投影；列出 `GridPattern.RowCount` 不表示 `GetItem` 也默认只读放行。扩大后台查询不改变 click 的 Legacy 权限门，也不证明各 provider 已实测无副作用。

属性不接收 args；无参查询只接收空列表；GetText 的 maxLength 必须为 1–6001 的整数且非 bool，拒绝 -1 的无界取全文。调用显式 GetText 后若返回长度达到请求上限，加 `possibly_truncated=true`；按 Windows UTF-16 code unit 长度作保守检查，不能因为结果未占满 6000 个 Python 字符就声称取得全文。`possibly_truncated` 与 `result_truncated` 分开核对：前者标 API 取文上限风险，后者是服务报告的结果截断；TextRange 投影触及 API 上限时两者也可能同时为真，不能按互斥来源推断。任一为真都不能当完整文本。表中成员仍可能由有缺陷的 provider 实现，照样受 worker 总超时与副作用报告约束；若某个应用的已测 getter 会夺焦，memory 对该路线填 uses_foreground=true，并停止把它当后台方案复用。

### 4.4 UIA 结果投影与可执行案例

实现 `_plain_result(value, budget)`，所有读取和转换仍在 worker 的 UIA 上下文中。固定总文本上限 6000 字符、集合总条目上限 100、嵌套深度上限 4；这些是传输边界，不截断持久化知识。达到上限置 `result_truncated=true`，不得把片段称作完整数据。

| 返回类型 | 转换规则 |
|---|---|
| None/bool/int/有限 float/str | 保留原类型；字符串消耗总字符预算，不能用 str() 抹掉类型 |
| list/tuple、仅字符串 key 的 dict | 在总条目/字符/深度预算内递归投影，保持顺序；遇未知类型按下行失败 |
| UIA Control | 调 `tree.describe` 转元数据并剔除 `_el`；保留 control_type/name/automation_id/rect/原生句柄等已取到的普通字段 |
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

**历史输入断路与当前适配：**通用 `args` 不能表达列表内 null 或 Control 引用，返回的 Control 元数据也不是可回传的元素句柄；这曾使 `ItemContainerPattern.FindItemByProperty` 的 NULL 首轮和引用续项都无法调用。本轮通过 §4.7 的专用 find_items 在同一 worker 调用内处理两者，不放开 invoke_pattern 的任意参数或跨请求 COM 缓存。其他需要 Control 输入的方法仍须保留具体适配缺口，不把字典伪装成 Control、不提供原始指针，也不把工具缺口报告成应用未暴露。

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

#### 4.5.1 本轮修补：兼容字符串的精确组合 target

`click`、`type_text`、`scroll`、`invoke_pattern` 及新工具 `find_items` 的 target 扩展为严格字符串或普通 selector dict，其他参数和默认值保持。字符串沿用 §4.3/§4.5 的现有匹配规则；不得借此改变日常动作的字符串优先级，通用 invoke 的字符串仍只允许精确匹配。selector 只含以下可选字段：

| 字段 | 严格类型和语义 |
|---|---|
| `name` | str；与当前元素 name 区分大小写精确相等 |
| `automation_id` | str；与当前元素 AutomationId 区分大小写精确相等 |
| `control_type` | str；使用 `see.elements[].control_type` 的原值，不把 Button/编号等猜成同义类型 |
| `native_hwnd` | 正 int，排除 bool；与当前 UIA 元素的真实 NativeWindowHandle 精确相等 |
| `rect` | JSON list，恰好四个严格 int，排除 bool；屏幕 `[x,y,width,height]`，width/height > 0，与当前树矩形精确相等 |

至少有一个非空 name/automation_id/control_type 或正 native_hwnd；空对象、仅 rect、全空字符串、null、未知字段、nth/index/contains、元组矩形、错长度、负/零宽高，以及数值字段中的 bool/浮点/字符串数字均拒绝。name="123" 等严格字符串仍合法。其他已提供的空字符串仍是匹配谓词，不得丢掉；所有字段 AND，不归一化、不按字段优先级降级，不做最近矩形或旧坐标点击。

实施落点与顺序：

1. `tree.target_error(target)` 集中返回 None 或校验错误文本；`act`、通用 invoke、共享 resolver 均复用。`server.py` 用 strict 字段和禁止 extra 的 selector schema，在框架强制转换前拒绝错类型；内部入口仍校验。先验证 target，再进入 provider，不能靠 Python 的 bool 是 int 子类而接受 `native_hwnd=true`。
2. selector 在本次 worker 的已初始化 UIA 线程读取完整当前树，检查所有字段并计数。唯一一项才返回；无项 no such control，多项 ambiguous target；树超时、触顶、identity_complete=false 或任何所需字段读取失败返回 tree incomplete，均在动作前拒绝。字段诊断按实际谓词决定：未请求的可选 rect/native HWND 读取失败保留 warning，请求该字段却读不到时不能把节点当作不匹配排除，以免掩盖第二个候选。
3. rect 是附加消歧条件，不是独立定位或点击入口；例如当前树给出同名同 id 的两项时，可增加 control_type/rect/native_hwnd 得到唯一结果。重新布局后旧 rect 不再匹配即拒绝，不能移除 rect 再发动作。客户端传入的字段只表达条件，不证明当前元素仍有效；不保留 `_el` 或其他 COM 对象到父端/下一请求。
4. 结构化 click/type 先完成全部谓词匹配，再将命中元素真实 native HWND 与本次 `win32.children(hwnd)`、既有允许控件类核对。确为目标窗口的可用原生 child 时才走现有后台消息路线；没有可用 child 时保留 UIA 的 allow_foreground 门。不得只按传入 native_hwnd 直接发送，也不得忽略 name/rect 等其余条件。通用 invoke 与 scroll 继续遵守各自权限规则。
5. server → worker → act/invoke 传递普通 dict，使用既有 JSON 帧和固定分发表，不更改 worker 的协议或缓存 COM。只对 invoke 的显式字符串 `target=""` 使用根直读；空对象或省略该必填 target 不获得根语义。必须在真实工具 schema、包装转发、worker 分派和内部 resolver 四个层次验证兼容性。

示例仅示意数据形态，字段值必须来自现场当前树，不作为任何应用的实测：

```python
invoke_pattern(hwnd, "LegacyIAccessiblePattern",
               {"name": "结果", "automation_id": "item", "rect": [10, 40, 200, 24]},
               "Name", [], False)
```

### 4.6 启动隐藏必须先证明窗口归属

当前 launch 的两段循环会隐藏观察期内**所有**新出现的可见顶层窗口，还会无条件争回前台。这个已核对的实现边界不能只改成一条免责声明；本轮必须修正，否则一次正常启动可能干扰同时出现的无关窗口。保留 open_app 公开签名、实际启动能力和 hidden_windows 原有 hwnd/class/title/still_visible 字段，按以下步骤修复：

1. 启动前用内部 EnumWindows 枚举全部顶层 HWND（包括隐藏窗口），形成 baseline；不能用仅含可见窗口的 windows() 证明“启动前不存在”。保存启动前前台 HWND 及其进程身份。
2. `Popen(..., shell=False)` 成功后，立即用 OpenProcess/GetProcessTimes 保存启动器的 `(pid, process_created_at)` 及持有的进程句柄；新句柄需在 finally 关闭。复用 appinfo 的进程查询/ctypes 声明，时间采用原始 FILETIME 整数以避免浮点丢失。无法读取创建时间就标未知，不猜。
3. 用 Toolhelp 进程快照取 th32ParentProcessID，只将已核验父进程身份、创建时间/时序相容的观察到的子孙纳入 owned 集合；期间持有相关进程句柄。PPID、相同 exe、窗口标题或“启动后出现”单独都不构成归属证明。父链漏采、PID复用、权限拒绝保持未知。[S13][S14]
4. 两段循环共用 `_owned_window(hwnd, baseline, owned)`；每次隐藏前重新检查 HWND 当前PID/创建时间、非baseline。仅确认归属才 SetWindowPos，并检查API返回及实际可见状态；失败留错误。不相关或未知窗口不隐藏。只有当前前台也归属 owned，且原前台身份仍相同、仍可见非最小化时才回交前台；不能打断用户主动切到其他应用。
5. 单实例转交、URL/快捷方式/UWP broker 等没有可核验归属链时，启动请求仍可成功，返回 unknown 的候选供 skill 继续 windows/see 定位；不隐藏既有窗口、不杀进程、不伪造“已后台启动”。当前 Popen 不具备通用 ShellExecute/URL/LNK 解析契约，不能凭输入扩展名承诺此能力。accessibility flags 仍保留，实际是否由目标采纳另行核对。

返回保留原字段，追加 `target_window_confirmed: bool`、`visibility_control: "applied" | "partial" | "unconfirmed" | "not_requested"`、`window_candidates: list`、`warnings: list`。hidden_windows 中追加 pid/process_created_at/ownership_basis（direct_process 或 observed_descendant）/hide_succeeded；pid 顶层字段明确仍是启动器PID。applied只描述已确认窗口上的隐藏结果，不保证应用永不重新显示；部分隐藏失败用partial，无归属证据用unconfirmed，show=true用not_requested。候选最多200项，带ownership=unknown/reason和候选截断标记，不把无关新窗口混成已确认目标。

这项修复扩大可靠定位能力，不能以禁止单实例应用启动来规避归属问题。GUI 验证同时创建本轮目标与一个无关测试窗口，后者的隐藏/激活调用计数必须为零；再覆盖已证实子进程、转交、查询拒绝与PID/HWND复用的mock分支。

### 4.7 find_items：同调用引用、有界匹配序列与完整性边界

新增 `deskweft/items.py`，公开 MCP 工具由 server 严格包装，固定 worker 分派指向 `items.find_items`：

```python
def find_items(hwnd: int, target: str | dict = "", property_id: int = 0,
               value: bool | int | float | str | None = None,
               start_index: int = 0, max_items: int = 100,
               timeout_ms: int = 8000) -> dict: ...
```

它调用 ItemContainer 的 FindItemByProperty，服务端以 NULL 开始，在当前 worker 调用内保存后续原始元素引用；引用不返回客户端、不跨调用复用。windows-mcp 0.8.8 的该 wrapper 会直接解引用 `control.Element`，不能处理 NULL；专用实现取得已核验 ItemContainer wrapper 的原生 pattern，在内部构造 VARIANT 并执行该固定接口。客户端不能选择任意 COM 接口、指针或表达式。只查询，不调用 Realize、滚动、选择或焦点操作；没有 allow_foreground 参数，但仍采样副作用并受 worker 总期限约束，不能承诺错误 provider 永不夺焦。

#### 4.7.1 参数与目标

| 参数 | 严格契约 |
|---|---|
| hwnd | 合法窗口正 int，排除 bool |
| target | 默认空字符串直接取该 HWND 根；非空字符串与 selector 复用当前完整树的纯精确唯一解析，错误/歧义/不完整均拒绝 |
| property_id | 0..2147483647 的严格 int，排除 bool；0 表示无属性过滤，正数交 provider 判定支持性 |
| value | property_id=0 时只能 null；正 property_id 时仅严格 bool、int32（-2147483648..2147483647）、有限 float、最多6000字符 str，拒绝 null/对象/集合/NaN/Infinity |
| start_index | 0..10000 的严格 int，排除 bool；是**属性匹配序列**的偏移，不是可见树下标或应用数据行号 |
| max_items | 1..100 的严格 int，排除 bool；不为全量任务移除这个单次上限 |
| timeout_ms | 1..30000 的严格 int，排除 bool；整个 worker 请求预算，默认8000 |

Name=30005、AutomationId=30011、IsSelected=30079 是可向实际 provider 探测的属性例子，不承诺 provider 支持每项。过滤值保持 JSON 类型；false 不是0，整数不是字符串。所有校验先于 provider，server 不做宽松类型转换；内部函数也校验。根直读可作用于已核对归属且确有独立 HWND 的内容/child，不能猜一个句柄绕开定位。

#### 4.7.2 分页、循环和元数据

每次调用都从 NULL 重新枚举，跳过 start_index 个匹配项，返回最多 max_items 项，并取一个额外匹配项判断 has_more。最多执行 start_index+max_items+1 次 FindItemByProperty（更早遇到末尾/错误/期限会结束）；provider_calls 仅记录该接口次数，不代表总的 COM 属性/身份查询次数。后页需重扫前缀，必须计入定位→查询→验证成本，不能假设分页是常数成本。

跳过的前缀只用于定位，不交付其元数据。首100项加末3项仍只取得103项，不能因为provider扫描到末尾而声称取得300项。调用方应检查实际 items[].index 范围是否无遗漏，并以已验证业务身份去重计数；扫描过、返回过和业务已取得三者分别记录。

在同一调用内用可取得的 RuntimeId 和必要的元素身份比较检测重复/循环，覆盖 RuntimeId 缺失与恢复的混合情况；发现重复返回 provider cycle，不把重复项当新数据无限遍历。RuntimeId 只支持本次枚举身份/循环证据；虚拟 peer 的生命周期可能使同一 AutomationId 的 RuntimeId 跨调用变化，不能存成稳定分页键或持久元素句柄。不同元素的同名值照常保留，不按 name/显示文本去重。

每项只投影下表，原始 COM 元素留在 worker：

| item 字段 | 来源与边界 |
|---|---|
| index | 本次匹配序列的索引，含 start_index 偏移 |
| runtime_id | 当前原始元素 GetRuntimeId 的整数列表，取不到时为 null；不保证跨调用稳定 |
| name / automation_id | CurrentName / CurrentAutomationId 的普通值，字符串受本次总6000字符预算约束 |
| control_type | CurrentControlType 的数值 UIA 类型 id；不同于 see 元数据中用于 selector 的字符串 control_type，不自行转换为同义值 |
| is_offscreen | CurrentIsOffscreen 读到的 bool/int；离屏虚拟项可能在此 getter 抛错，其他已读字段仍保留 |
| read_errors | 逐字段错误文本，字段失败则值为 null；保留异常类型与消息，每条最多160字符，不因可选字段错误丢掉整个元素 |

字符串共用总预算，字段超出剩余预算才截断，置 result_truncated=true 并立即返回该项；next_start_index 指回该项索引，供缩小页/改读法后重读。元数据 getter 失败设置 metadata_complete=false，仍保留其他字段和后续项目。不把错误/截断值写成完整数据。

任务必需字段与附加元数据应分别判断。例如 name/automation_id 已读而 IsOffscreen 报错时，保留名单与字段诊断，分别报告业务字段覆盖和附加元数据缺失；metadata_complete/complete 仍为实际 false。不得丢掉已读数据、自动 Realize/滚动或无限重试来换取干净标记。

#### 4.7.3 返回、失败与“完整”的含义

成功使用 `_done(..., action="find_items", route="uia:ItemContainerPattern")`，保留共同执行/前台字段及 `call_completed=true, effect_verified=false`。以下为查询开始后汇总返回的普通数据字段；参数校验在此前拒绝时只需共同错误结构：

| 字段 | 含义 |
|---|---|
| items / returned_count | 当前页已经投影的项目及其数量 |
| start_index / property_id | 本次请求的匹配偏移和属性 id |
| provider_calls | 实际 FindItemByProperty 调用次数，含跳过前缀和前瞻 |
| has_more | 已看到额外项为 true；已看到 provider NULL 为 false；出错/截断等未判断时可为 null |
| next_start_index | has_more=true 时为 start_index+returned_count；无后续证据时一般 null；文本截断时可指回当前未读完整项，不是持久游标 |
| reached_end | 只在 provider 明确返回 NULL 时 true；表示本次查询的后缀结束 |
| metadata_complete | 已返回项目的指定元数据读取无错误；不表示 provider 覆盖了所有业务项 |
| result_truncated | 本次元数据字符串被服务预算截断；false 仍不表示业务全量 |
| complete | 仅本次无查询错误、start_index=0、reached_end=true、metadata_complete=true 且未截断时 true |
| snapshot | 固定 false；跨页查询不是同一时刻快照 |

完整性分两层：complete 只说明这次从头查询的 **provider 匹配序列及元数据**达到上述条件；UIA 不保证顺序稳定，provider 也可能跳过数据相等的业务项。reached_end=true 的后页仍 complete=false，多页拼接不自动获得完整标志。声称业务全量前，必须另核对独立可信总数/分区与终止边界、业务身份、重叠页一致性及动态变化。重复名称可以合法存在；AutomationId 必须经验证非空、在任务范围唯一且代表稳定业务身份才可作跨页键，模板复用值/行位置编号/临时标识均不自动获得这个含义。

定位/模式失败保留 no such control、ambiguous target、tree incomplete、pattern not wrapped、pattern unavailable 等原诊断，在调用枚举前报告 not_started。查询中 provider 异常返回 provider error，已访问元素循环返回 provider cycle，正常检查点超预算返回 query budget exhausted；携带已投影部分结果且 complete=false。单个阻塞 COM 调用仍由父端 worker deadline 回收，结果 execution_state=unknown，不自动重放。元数据字段错误不伪装 provider 无能力，也不通过自动 Realize/滚动来掩盖错误。

示例只表示合法工具参数，HWND/selector/属性须现场核对：

```json
{"hwnd":123456,"target":{"automation_id":"members"},"property_id":0,"value":null,"start_index":0,"max_items":100,"timeout_ms":8000}
```

```json
{"hwnd":123456,"target":{"automation_id":"members"},"property_id":30005,"value":"Alice","start_index":0,"max_items":20,"timeout_ms":8000}
```

第二页正常可使用返回 next_start_index；若为稳定性核对选择重叠页，要明确记录偏移和相邻业务身份。next_start_index 不前进、数据变化或元数据始终不可读时，不无限重复同一查询，保留 partial 并比较其他已获授权方向。真实WPF夹具的结果、失败和环境在 [本轮测试报告](../reports/2026-11-08-itemcontainer-live.md) 维护，不把夹具结果推广为 QQ/Electron 或其他 provider 的保证。

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

````markdown
---
name: windows-app-automation
description: Use when automating or probing Windows applications, including native controls, UIA/Legacy, Electron, UWP/WinUI, self-drawn interfaces and virtualized lists; when reads/actions fail; or when choosing an official API, CLI or export instead. 控制陌生软件、读不到界面、点击不生效、完整列表采集、自动化路线选择。
---

# Windows 应用自动化

本skill是DeskWeft的路线层，与本地memory和受控MCP执行层配合使用；目录名仍为`windows-app-automation`。改名前取得的实测按其原版本与条件保留，名称变化不构成重新验证。

## 路线顺序：先后台，再在同层比较效率

对满足同一任务范围、正确性和授权条件的候选，严格按以下四级顺序选择与试验。
此顺序也约束已有可用路线、历史高 rank 路线、专用工具、通用入口及后文全部操作库：

1. **后台高效**：全闭环保持目标在后台，完整成本在同类后台候选中较低。
2. **后台低效**：仍能保持后台，但完整成本较高；它仍优先于任何前台高效路线。
3. **前台高效**：需要或可能接管前台，且完整成本在同类前台候选中较低。
4. **前台低效**：需要前台且完整成本较高，保留为有依据的最后候选。

只在同层、同目标范围、同正确性/覆盖率和可比环境下比较完整成本，不能用更快的
前台方法跨过仍可行的后台方法。“高效/低效”依据用户阈值或可说明的相对实测，
没有阈值就报告实际数据与比较对象，不编造毫秒线；成本未知先标待测，不因未测就
把它当低效并跳过。已有的前台基线可以保留历史结果，后台任务不能为“先有基线”
再执行一次前台动作。已满足完成标准时无需为跑完四层而执行更低层或重复副作用。

完整成本包含保护安装/验证、准备、目标定位、worker/IPC、实际调用、必要等待或
轮询、效果验证，以及保护撤销/状态恢复；同时记录调用次数和全树次数。一次性准备
与重复调用分别列出，说明摊销口径，不拿一次暖调用与另一路冷启动直接比。
无固定 sleep 只说明省去那段固定等待，仍需验证最终状态，不能当作零等待、零验证
成本或天然更高效。精确 selector、Legacy、原生消息和 API/CLI 都须按完整闭环实测。

降到下一层前，逐条给出上层合理候选的降级理由：不适用、定位/能力缺口、保护
不可用、权限不覆盖、效果或完整性失败、稳定性不满足，或有证据的试验成本。
“前台更快”“已有授权”“已有一条能用”“某个后台方法失败”都不是跳过整个后台层
的理由。同层被另一候选在相同约束下完全支配、且无额外诊断收益时可有据跳过；
写明依据，不机械重放。无需穷举所有技术，但有根据、适用且可继续的后台候选不能
只记为未试就转前台。若只能前台完成，报告已降级，不能改称后台完成。

## 后台试验：先保护，再调用，再验证

后台探测必须在调用前先阻止应用抢前台，保护覆盖本次窗口/进程、定位、读取/动作、
效果验证和可能延后的异步处理，不能等发现抢焦后再处理。先确认现场是否存在已经
实现、适用于该目标且验证生效的防抢焦能力，再发出调用；记录机制、作用范围、
生效证据、准备/撤销成本及失效条件。本文不承诺当前工具已经提供这样的保护。
工具返回某个开关已设置、窗口看起来被禁用或隐藏，都不是保护已有效的证据。

需要调查保护能力、实现隔离候选或审核防抢焦证据时，读取
[前台保护调查与验收](references/foreground-protection.md)。随包独立桌面入口已在本机
QQ 9.9.22 完成显式语义登录、直接搜索读写、恢复与清理的复验，可作本环境普通激活
路线的复用起点；其他环境或动作仍先满足调用前验收条件，生产 MCP 本身没有自动
隔离能力。

最小验收记录要能回答：能力当前是已实现还是缺失、保护约束通过什么可检查状态
生效、覆盖哪些进程/渲染子窗口及调用 worker（涉及 session/desktop 时也核对归属）、
如何发现保护失效并停止继续发动作、怎样在不放行抢焦的条件下安全结束实验。
只有配置成功、没有报错、没有收到事件或等待了一段时间，不足以独立证实阻止能力。
缺少可检验的约束/失效/退出依据就保留工具缺口，不拿真实用户输入前台冒险补证。
已发出的异步动作需有实际完成、可靠取消或所有相关处理已终止的证据，才能按该
机制的契约撤销保护；queued、超时、固定 sleep 或一次状态不变都不是终止证据。
查不清时保持执行未知并继续受保护的状态调查，不能先撤保护、让延后动作接管前台。

allow_foreground=true 不是防抢焦保护。它只满足某些工具的权限门，不会阻止 provider
激活窗口，也不会把后台试验中的抢焦变成获准的后台结果。已有广义前台实验授权
继续有效，无需为同一范围重复确认；它仅允许在前台层执行相应实验，不能降低后台
层的保护要求。allow_foreground=false、只读白名单、Get 前缀、方法名或 API 返回值
也都不是防抢焦机制；只读 getter 已知会抢焦时，不能再凭白名单从后台重试。

保护不可用、无效或尚未验证时，不发出潜在抢焦动作，包括已证实抢焦的 SetValue、
Invoke、SetFocus、选择/展开/滚动等及副作用未知的 provider 调用；记录具体保护/工具
缺口，继续其他后台只读候选。继续候选仍须核对它自己的副作用与保护，可以先做
不触发该 provider 的窗口/进程身份、接口和代码调查，或使用有适用证据且保护有效
的独立只读通道，不能把换成 getter 当作绕过前置保护的理由。不因此结束整个任务、
把未调用记作调用失败，或断言应用不支持后台。若所有合理后台候选当前都受阻，
说明各自原因后才进入既有授权覆盖的前台层；没有前台授权则只阻塞相应前台动作。

| 现场条件 | 本次决定与记录 |
|---|---|
| SetValue 已证实抢焦，现无有效保护，即使已有前台实验授权 | 不从后台调用；标为已知前台副作用/后台保护缺口，继续其他后台候选 |
| 新保护据称已开启，但本目标尚未验证有效 | 仍不能发潜在抢焦动作；先核验保护能力，不拿真实用户前台作无保护试验 |
| 保护已生效，但动作效果被阻断或结果未知 | 如实记本条件失败/执行未知，先只读查状态；不解除保护后冒称后台成功或自动重放 |
| 后台候选均有具体受阻依据，且已有前台实验授权 | 明确降级到前台层，沿用该授权并测效果与完整成本，不反复请求同一许可 |

先抢焦再切回原应用是事后恢复，不是防止抢焦；即使恢复很快，也记录“发生抢焦，
随后恢复”，把恢复成本计入前台路线，不能充作后台成功。`before==after`、
foreground_changed=false 只描述工具记录的两个采样端点，不能证明全程前台未变。
若要评价整个闭环，保存覆盖该时段的前台事件/时序观测、鼠标观测及其覆盖范围、
采样间隔/丢失可能和异步观察窗口；观测本身仍不是阻止机制。只有端点数据时写
“前后采样相同，期间未知”，不编造连续监测或绝无副作用的保证。

## 开始前：确认目标和实际可用工具

1. 看客户端实际工具清单；本文中的新增工具未注册时记作“工具尚未实现”，
   不编造调用。用 windows() 确认 hwnd、pid、标题与类，app_info 确认 exe/版本来源。
2. 已知版本时 recall("name@version")；未知时 recall(name) 看候选。
   先排除不适用的版本/环境和当前不允许的副作用，再按 rank 看。
   uses_foreground=true 的路线不能当后台候选，即使已有前台实验授权也不改变层级；
   未获授权的前台路线另行排除，用户离开也不自动构成授权。
   已明确取得的本次授权按其范围继续使用，不为同一动作反复请求确认。
3. 精确、本版本、非继承的 rank>=2 可复用路线，但仍验证每次目标效果；
   rank=1 逐步验证；rank=0、家族/继承候选或未命中先探测。
   正文截断时用 plan_id/body_offset 续读，核对每片 revision 一致，再拼完整步骤。
   reviewed/proven 不是本次业务操作授权，不能据此关闭、提交或重启应用。
4. rank 表示已有证据的可信度，不表示效率、任务覆盖率或本次最优选择。
   已有可用路线先分类为四级基线，执行仍遵守顺序；用户要求后台、高效或全量时，
   还要按下节核对适用备选，
   不能因 rank 高、曾经成功或已经取得部分数据就宣布目标完成。

## 任务范围、路线台账与结束条件

先把用户目标落实为可观测结果：要读或改变什么、当前项还是完整列表、总量的来源、
必须包含哪些字段、是否允许前台/鼠标变化，以及用户给出的时间或调用成本要求。
“后台读取”和“允许为实验夺焦”分别记录；实验获准夺焦不代表所得路线满足后台目标。
没有给出性能阈值时记录实际成本和比较依据，不自行编造预算或默认允许重启、导出、
提交等额外副作用。能从现有授权与只读观测确认的条件先确认，不反复向用户询问。

为本次任务维护一份候选路线台账，可直接写入 memory 的 `## 实测记录` 和
`## 未试方向`，无需另造交接文件。每条路线至少记录：

| 字段 | 要记录的内容 |
|---|---|
| 路线与适用依据 | 工具/接口、目标 HWND/selector、版本及启动条件；为什么能覆盖当前任务 |
| 层级与效率依据 | 后台高效/后台低效/前台高效/前台低效或成本待测，完整成本比较对象与范围；不把可信 rank 当效率 |
| 状态与原因 | 已验证、已试失败、未试、权限阻塞、工具缺口或不适用；保留实际错误，未试不能写成失败 |
| 任务覆盖 | 取得的字段、唯一条目数/目标总量及来源、当前项/可见页/全量范围、截断或缺失 |
| 完整调用成本 | 保护/准备→定位→读取/动作→必要等待→效果验证→撤销/恢复的全链路耗时、工具/全树次数、样本及摊销口径 |
| 后台保护 | 调用前机制是否实现并已核验生效、覆盖窗口/进程与异步范围；不可用时为何没有发出该动作 |
| 副作用证据 | 前台/鼠标事件或采样及覆盖范围、用户可见变化、抢焦与恢复；端点相同不代表全程未变，未观测写未知 |
| 降级理由 | 上层各合理候选的适用性、保护、权限、效果/覆盖或成本证据；一条失败不能替其他候选作结论 |
| 下一步或停止依据 | 尚缺的验证、所需权限/工具、继续的预期收益与成本；无法比较的指标写未测 |

按以下顺序推进，不要求穷举所有技术或完成固定次数的试验：

1. 将已有可用路线与新候选先归入四级，再在当前最优可行层验证任务效果和完整成本。
   保留可回退基线，但不为了复现前台基线跳过后台层；后台试验先满足调用前保护。
   没有可用路线时在许可及保护范围内建立最小闭环，不把探测返回成功当作业务成功。
2. 结合当前观测检查有根据的候选：明确 native child 的直接查询、可唯一定位的
   UIA/Legacy 只读成员、列表的其他访问方式，以及已有官方 API/CLI/导出或合法浏览器
   语义接口。表中的各类路线用于核对适用性，不代表要实际调用所有接口。
3. 对已经发现、适用、低成本且获授权、可能推进未完成目标或改善用户所要求成本的
   备选，按四级顺序并在保护条件具备后实际验证；不能只把“未试”写进台账就结束。
   已知抢焦但无保护的动作不发出；其他候选写明可核实的跳过原因，
   如无对应控件、能力未封装、权限不足或可说明的试验成本；不能凭猜测把它们排除。
   只读替代仍可调查时，某个动作缺少权限只阻塞该动作，不结束整个任务。
4. 用相同任务范围比较正确性、覆盖率、稳定性和副作用，完整成本的优先选择只在同层比较。
   不把只读一个名称与读取全名单比较，也不只计 Invoke/消息本身而漏掉反复读树的时间。
   精确 selector 仍可能触发树遍历；只有实测减少了全树读取或总耗时才能声称提速。
5. 满足用户的完成标准，并已处置上述有根据的适用备选后，可结束；只声称“本版本、
   本次已测候选中满足约束的最佳路线”，列明比较范围和未试原因，不声称全局最优。
   目标仍未完成时，先继续当前许可内有望推进目标的合理调查；确有权限/工具缺口、
   已验证的路线限制或用户预算边界时，报告 partial/未达成和具体下一步，不能用
   “已有一条能用”“一次空树”“一次滚动不变”充当整个任务的完成或结束依据。
   某条候选受阻不自动阻塞其余候选；因目标未达成而结束时，说明剩余有根据的方向
   为什么当前都不能继续。用户未给预算上限时，不能自行以“预算用尽”跳过可行调查。

结束报告区分：已完成的任务范围、实际结果与完整性证据、已测候选的成本和副作用、
未试/阻塞方向与原因。部分结果可以交付，但不能把交付 partial 本身当作全量目标完成。

## 基础探测：把不同原因分开

1. see(hwnd, with_tree=true) 同时看截图、elements、native_children、timed_out。
   先核对窗口身份是否变化、是否隐藏/最小化、是否触及元素上限。
2. 空树可能来自过滤、超时、provider 错误或启动条件；不能仅凭空结果判框架。
   截图空白与树不可读是两个问题，分别试验并分别记录。
3. 读取先用明确只读接口；写操作先用 click/type_text 等现有专用工具。
   需要通用模式/原生消息时按各自权限和数据契约执行。目标未知、重名或树不完整时
   不调用 click 去碰运气；用下面的精确组合 selector、明确 child HWND 或记录定位缺口。
4. 每次失败写清“未试、权限未满足、工具缺能力、provider报错、调用完成但效果未达成”
   中的哪一种；某一条路线失败后按下表换方向，不能推成整个应用无法自动化。
   queued/unknown 的副作用动作先按后文查清状态，不能借“换方向”重放同一业务动作。

## 控件目标：保留字符串路线与精确组合 selector

支持 target 的控件工具可继续传字符串，也可传对象：
`{name?, automation_id?, control_type?, native_hwnd?, rect?: [x, y, w, h]}`。
click/type_text/scroll 的旧字符串路线保留既有唯一子串回退语义，不能把所有字符串
都当作纯精确匹配。`invoke_pattern` 的非空字符串只按精确 AutomationId、再精确 name
定位；组合对象的所有字段在各工具中都按 AND 精确匹配，不作模糊、包含或大小写猜测。
组合 selector 不支持 nth、索引或用坐标猜点击点。

- 对象至少有一个非空的 `name`、`automation_id`、`control_type`，或正整数
  `native_hwnd`；bool 不能充当 HWND。只给 `rect` 不能定位，空对象不能定位。
- `rect` 是从当前树元数据取得的 `[x, y, w, h]`，只能附加在上述定位字段上作精确
  消歧；`rect + native_hwnd` 有效。它不是坐标点击入口，不从截图猜框、不选最近项。
- `native_hwnd` 必须属于当前目标窗口读树/原生子窗口中的实际元素，不能把任意句柄
  当作绕开窗口归属或唯一性校验的入口。直接原生消息仍遵守 post_message 的独立契约。
- 例如同名按钮可用 `{name: "确定", control_type: "ButtonControl", automation_id: "confirm"}`
  消歧；只有现场树确实提供这些值时才使用示例中的字段，不编造 AutomationId。
  `control_type` 直接复制 `see` 元数据中的值，如 `ButtonControl`/`EditControl`，不自行
  去掉 `Control` 后缀或改写成 Win32 class 名。
- 全部字段必须在当下完整树中唯一匹配。无匹配、重名、树不完整或字段已变化时拒绝
  动作；重新观察并重新确认目标，不删除失败字段、不退回第一个同名项或旧坐标。
  保存 selector 只保存定位条件，不能把旧树里的元素身份当成本次验证。

`invoke_pattern` 的 `target=""` 是当前 hwnd 的根控件直读入口，不是匹配空名称或选择
第一个控件。只有已确认根控件确实承载所需 Value/Text/Legacy 属性时才采用，避免每次
为了定位根控件读整树；根只提供窗口标题时不能用它替代实际内容区域的读取。

## 按界面与任务选择路线

| 观测或任务 | 下一步思路 | 如何验证、何时换路线 |
|---|---|---|
| 原生 Win32/WinForms 子控件 | 从 native_children 取 child HWND/class，按钮和文本先用专用工具；必要时用托管 WM_GETTEXT/SETTEXT、BM_GETCHECK、CB/LB_GETCURSEL | 文本读回相等，按钮检查目标状态/计数，选择检查索引；入队不等于生效。没有匹配控件类时转 UIA，不推断整个程序不支持。 |
| 有语义 UIA 的 WPF/WinUI/其他应用 | 按工具契约使用字符串或精确组合 selector，按 provider 暴露的 Value/Text/Selection/ExpandCollapse/Scroll 等接口读取或操作 | patterns 的七项摘要不是全集；按需尝试其他已封装 pattern。明确区分目标歧义、未封装、未暴露和方法异常。 |
| Chromium/Electron/浏览器树空或失焦后消失 | 核对进程、已有 flags、前后台对照，再检查下面的无障碍与防降级条件；已有合法浏览器语义接口也可作为替代 | 重复读取同一窗口比较命名元素与稳定性，不把单次非空当长期有效；单实例不采纳 flags 时需真正的新启动条件。 |
| UWP/WinUI 壳窗口只有标题栏或空 Pane | 核对 ApplicationFrameWindow、原生子窗口及独立内容窗口，查找实际 CoreWindow/内容承载 HWND 后重新 see | 壳为空不证明内容无树；不能跨 PID 仅凭标题猜错对象。找不到承载窗口时记录定位缺口。 |
| 有树但点击/写入无效 | 先读取值/状态，排除动作仍在排队或执行结果未知；再比较已授权的 Legacy、Invoke、选择、展开等语义路线，确认真实目标与返回值 | Legacy 是候选路线，不保证所有应用都不夺焦；当前 click 的 Legacy 路由仍在前台权限门之后。某个 setter 静默返回时必须读回或观察实际效果。 |
| 自绘/Canvas/GPU 画面、树无语义控件 | 并行检查无障碍/Legacy、原生子 HWND、应用快捷键、官方自动化接口或导出；截图仅帮助观察 | 不假设当前有坐标点击工具；若需视觉交互而工具未提供，记录缺口或用已授权且确实可用的工具。截图不可用不证明其他通道不可用。 |
| 需要完整长列表/历史记录 | 检查搜索、展开、分页、滚动、Text/Selection；ItemContainer 用专用 find_items，VirtualizedItem 等按实际封装/授权探测，再比较应用导出/API | 每页验证新增项目并去重；find_items 是实时 provider 匹配序列，末页 reached_end 不等于业务全量，需重叠页和独立总量核对。未渲染内容不可从截图推断。 |
| UI 路线成本高或需要精确数据 | 检查应用已有官方 API、CLI、脚本/自动化接口、导出功能或浏览器语义工具；必要时采用已有合法 CDP 会话 | 这些是需要核对适用性的外部候选，不假装 DeskWeft 已内置。先核对能力、权限、数据来源与结果；已确认端口不可用时记录限制，不反复猜端口或绕过限制。 |

## 可执行候选路线：从观测到验证

以下是现场选择路线的操作库。按适用性和任务收益选取，不要求按编号逐项试完；
工具、成员或参数契约现场不可用时写清缺口，不编造调用或把建议当成实测结果。
这些编号不是绕过四级顺序的试验顺序；每条涉及的读取、动作、对照、导出和恢复
都先适用上文的分层、调用前保护及权限条件，局部“已有授权”不代表可以后台抢焦。

### 1. 已有明确原生 child HWND：绕过反复语义树定位

- 触发：`native_children` 已列出归属明确的 Edit/RichEdit/Static 等候选控件，任务是
  读取该控件文本或状态，现有路线每次都重读整树。
- 操作：首次核对 child HWND/class 与任务内容；对文本使用托管
  `post_message(hwnd=child_hwnd, msg=13, wait=true)`（WM_GETTEXT），需要时先用
  `msg=14` 查询 WM_GETTEXTLENGTH；实际 JSON 见后文调用小抄，不传消息名称字符串。
  勾选/当前选择分别用已允许的 `BM_GETCHECK`、`CB_GETCURSEL`、`LB_GETCURSEL`。
- 验证：保存真实 text/result，并与同目标的已知值、UIA 或业务状态核对；测定位与验证
  在内的完整成本。空字符串可能是合法空值，也可能读错控件，需按任务上下文判断。
  读取当前编辑框或当前选择不等于取得 ComboBox/ListBox 的全部项目。
- 权限/缺口：上述白名单查询可后台执行，不传指针。控件不响应或没有对应 class 就
  换 UIA/其他来源；不猜 LB_GETCOUNT 等其他消息也在后台白名单，不把读取升级为
  BM_CLICK/WM_SETTEXT 等动作来“试一下”。

### 2. 根控件承载数据或目标重名：缩短定位而保持精确

- 触发：已确认窗口根或独立原生子控件直接暴露所需文本/值；或多个控件同名，使旧字符串无法唯一定位。
- 操作：前者用 `invoke_pattern(..., target="", ...)` 直读根上的已允许成员；后者从
  当前元数据构造 `name + automation_id/control_type/native_hwnd` 的 AND selector，
  必要时附加当前 `rect` 消歧。优先使用能稳定区分业务目标的语义字段。
  已确认 native child HWND 合法且仍归属本目标时，也可传 `hwnd=child_hwnd, target=""`
  直读该控件的 pattern：当前实现接受合法 child HWND，并通过 ControlFromHandle 取其
  根元素，不必为此遍历整个父窗口。调用方仍需核对归属、返回控件和所需 pattern；
  无独立 HWND 的 UIA 元素不能假装可这样直达，句柄失效或 provider 不返回元素时换回精确定位。
- 验证：核对返回内容属于同一业务目标；记录完整耗时和全树次数。selector 能消歧
  不代表内部不遍历树，rect 变化后必须重新观察，不能沿用旧框点击。
- 权限/缺口：只读成员按只读契约，动作仍需其权限；找不到稳定唯一目标就保留定位缺口。
  根没有所需 pattern 时回到实际内容控件，不把根的空值推广为整个窗口没有数据。

### 3. 同一内容有 Value/Text/Legacy 多种读法：交叉核对再选成本

- 触发：某读法为空、慢、只给标题，或文本存在但字段/截断范围不清。
- 操作：在同一目标比较实际暴露的 `ValuePattern.Value`、Text 的
  `DocumentRange.GetText`，以及 `LegacyIAccessiblePattern.Name/Description/Value`。
  GetText 必须给有界参数，例如 `args:[4096]`；读取属性和 GetSelection 使用 `args:[]`。
  先确认各属性的含义，不把名称当正文。
- 验证：对照字段、长度、换行、业务样本和耗时；空 Description 只说明该属性为空。
  `possibly_truncated` 提示 API 有界文本可能不完整；`result_truncated` 反映整体有界化
  标记，自动 TextRange 投影触及 API 上限时也可能同时置 true，并非只表示传输裁剪。
  任一为 true 都不能证明全文完整。只有现场已有合法的 range/分页读取或其他完整来源才能补全，
  不能把一个有界字符串包装成“全文”；跨源不一致保留原值与原因，不静默拼接。
- 权限/缺口：这些只读成员按当前白名单执行，仍记录 provider 的前台/鼠标副作用。
  有文本但缺少可表达的 range 导航或返回值投影时，记工具缺口并比较导出/原生来源。

### 4. 当前选中项或表格结构可读：先明确覆盖边界

- 触发：任务涉及当前选择、表格行列或列表结构，界面只渲染部分数据。
- 操作：用实际封装且允许的 Selection/GetSelection、SelectionItem.IsSelected 读取
  当前选择；用 `GridPattern.RowCount/ColumnCount` 等只读属性摸底行列规模。
  保留 Control 返回元数据供定位核对，不把它当已取得每个单元格内容。
- 验证：Selection 只证明当前选择范围，不证明完整列表；Grid 行列计数是结构证据，
  需要确认标题行/隐藏行/过滤口径及 provider 是否只报告已加载部分。计数与可见行数
  不一致时调查虚拟化和分页，不能用一个 RowCount 就宣称所有行已读取。
- 权限/缺口：`GridPattern.GetItem` 的行列参数已可用 `args:[row,column]` 表达，
  但该成员不在默认只读表内，调用必须带 `allow_foreground:true` 且已有授权覆盖。
   有现成封装和授权时可列入相应层级的通用入口候选，不需等待参数适配；后台试验
   仍需先有有效保护，否则仅能在获准的前台层试验。默认无授权后台访问仍需后续
   只读契约扩展。选择、全选和改变当前单元格属于另一个动作。

### 5. 虚拟化列表暴露专用 pattern：区分 provider 能力与适配缺口

- 触发：可见项目少于业务总量，但 provider 暴露 Scroll、ItemContainer 或
  VirtualizedItem 等能力。
- 操作：先读取可用的滚动位置、可滚动状态和可见项目；ItemContainer 用下文
  `find_items` 从 `property_id:0,value:null,start_index:0` 开始有界查询，再验证后续页。
  同时按已授权、已封装的 Scroll/Realize 或其他容器方法试最小分页闭环；每步读取
  新增项目和位置变化，不能把 find_items 的只读契约套到 Realize/滚动上。
- 验证：按业务 id 去重，记录访问范围和边界。Scroll 报不可滚动可能只针对当前容器；
  核对是否选中了真正列表。某次容器查询若只返回一个 Control 的元数据，仅证明该项
  可定位，不能推断后续全部可遍历。
- 权限/缺口：Scroll/Realize 等改变状态的调用不因读取目的变成后台只读。
   即使已有动作授权，也先按四级顺序和后台调用前保护决定能否调用。
  早期通用 args 不能传 null 或 Control，曾使 ItemContainer 首轮和续项都断路；
  本轮 `find_items` 已专门托管同调用内的 NULL 起点与元素续项，不需客户端传引用。
  其他任意方法的 Control 输入仍未实现，不伪造元数据引用；provider 不支持或查询
  结果不完整时，保留原因并继续核对其他读取、分页或导出来源。

### 6. 应用提供搜索、筛选、分页或分段导出：验证分区能覆盖全量

- 触发：单页/滚动路线无进展，应用中有可定位的搜索框、页码、下一页、类别或导出范围。
- 操作：先只读确认这些功能、当前筛选条件和总数含义；在既有授权覆盖的范围内使用
  内置分页或可解释的分区查询，或选择全量/分段导出。记录原始筛选和恢复条件。
- 验证：每页/分区检查新增 id、页号/游标变化及终止边界；说明分区是否穷尽、有无重叠，
  并去重。导出的“当前页”“当前选择”“筛选结果”“全部记录”范围必须核对，
  结果总数、字段和抽样记录应与业务口径一致。
- 权限/缺口：改搜索词、筛选、选择、分页、滚动或写出文件可能改变用户工作状态，
   依其层级、调用前保护、工具与既有授权执行，不擅自清空用户筛选。
   不能因搜索框用途安全就无保护调用已知抢焦的 setter。无足够授权先保留原状态、查只读替代，
  记录具体需要的动作；不把未经证明能穷尽的关键词搜索称为全量方案。

### 7. 官方 API/CLI、应用导出或本地文档输出：避免逐项 GUI 采集

- 触发：任务需要大量准确字段、重复 GUI 成本高，或应用已有结构化输出能力。
- 操作：核对应用/版本提供的官方 API、CLI、脚本自动化、导出或用户已授权的本地文档
  输出；有合法浏览器语义/CDP 会话时也可比较。优先使用已存在的接口和访问凭据，
  不假装这些由 DeskWeft 内置，不自行启用调试端口、抓取私有数据库或绕过访问限制。
- 验证：保存来源与时间，核对分页/游标、总数、字段、去重与截断；本地文档需要确认
  文件确已写完、读的是本次输出且范围正确。先用任务样本与界面交叉核对，再据完整
  来源取得全量；把导出/请求/解析/验证时间都计入成本，而不只计最终读文件时间。
- 权限/缺口：调用与输出需符合当前用户授权和实际可用工具；创建导出、触发提交或
  读取额外敏感来源不从“需要高效率”自动获得许可。没有可用接口时记清文档/能力限制，
  已确认端口不可用就不反复猜测；不得因此抹掉其他 UIA/原生候选。

### 8. UWP/WinUI 外壳没有内容：定位真正内容宿主

- 触发：`ApplicationFrameWindow` 只有标题栏或空 Pane，但应用画面明显存在。
- 操作：用窗口/进程信息和 native_children 查找 CoreWindow、独立内容窗口或实际承载
  HWND，核对归属后在该 HWND 重新 `see`，再试匹配内容的只读接口。
- 验证：比较内容字段、命名元素和业务状态，确认读的是同一应用页面；标题相同不足以
  证明跨 PID 的窗口属于同一目标。宿主定位成功后重新记录实际 hwnd/pid 和读取成本。
- 权限/缺口：定位与读取不要求揭示隐藏窗口。宿主无法确认就记定位缺口；不能跨 PID
  猜窗口，也不因壳空就宣称整个应用没有无障碍树。

### 9. Electron/Chromium 后台降级：按启动条件作单变量对照

- 触发：已确认 Electron/Chromium，树在失焦、被遮挡或后台状态下消失/缩水。
- 操作：先核对活动进程、实际 flags 和前后台窗口状态，比较同一目标的重复读取；
  再按后文已知无障碍、防遮挡参数及 GPU/软件渲染假设选择有依据的对照。
  每次只改一个条件，记录基线、预期、耗时和回退；启动后验证新参数真的进入活动进程。
- 验证：同时看命名元素、任务字段和稳定性；一次非空不代表后台长期有效，像素变化
  不代表列表新增。树恢复、动作生效和完整采集是三个独立验证目标。
- 权限/缺口：需要新实例或重启时先确认授权和未保存工作；单实例忽略 flags 不能假装
  对照已成立。reveal 会夺焦，GPU/flags 更改有副作用，按授权执行；未获授权就保留
  假设并推进无需该变更的候选，不能默认关闭/杀进程或一次堆叠多个未知 feature。
   前台对照归入前台层；持有重启/前台实验授权也不能把它排在可行后台候选之前，
   更不能把重启后曾获前台的测量归为无抢焦后台路线。

### 10. 后台看不到或一次读取失败：比较状态与读法，保留执行未知

- 触发：截图空白、UIA 空树、某属性为空或动作后计数暂未变化。
- 操作：分别核对窗口身份、可见/最小化、timed_out、元素上限和 provider 错误；
  对同一目标比较已有 UIA/Legacy/原生只读来源，能合法读取时查询
  `WindowPattern.WindowVisualState` 辅助判断状态。前后台对照只在现有授权允许时进行。
- 验证：分开记录“看不到画面”“树不完整”“数据属性为空”“动作未观察到效果”，
  保存每条来源实际结果。只读状态通道恢复不代表先前动作已执行或绝对未执行。
- 权限/缺口：WindowVisualState 的读取不等于获准恢复/最大化窗口；揭示、切前台、
  SetFocus、重启都须各自授权。queued/unknown 时只调查状态，不换工具重放同一副作用。
   这些动作以及只读状态通道都服从后台调用前保护；没有有效保护时，先继续不触发
   潜在抢焦 provider 的独立调查，不以已获广义前台授权代替保护。
  没有独立状态通道时报告具体未验证部分，不推广为应用没有后台能力。

### 11. pattern/返回值/参数无法表达：留下可实施的工具适配工作

- 触发：已看到 provider 能力，但得到 `pattern not wrapped`、`result unsupported`，
  或需要 Control 引用/受控参数而现有 args 契约无法表达。
- 操作：保存 pattern_id、成员、所需参数类型、真实错误和已投影结果；查当前封装能力
  与工具版本。把后续工作写成具体缺口，如补 pattern 包装、增加某返回类型投影、
  安全的 Control 引用传参/失效校验，或扩展特定只读成员的参数校验与测试。
- 验证：适配前只声称调用到了哪一步；`result unsupported` 可能发生在执行之后，
  不自动重试。适配之后仍需重新验证业务效果、覆盖率、成本与前台/鼠标副作用。
- 权限/缺口：记录适配工作不等于本次自动获得修改工具、安装依赖、放宽白名单或
  重启应用的授权。当前任务可继续其他已可用路线；工具暂不支持不能推成应用不支持。

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
reveal(hwnd) 是显式恢复隐藏窗口的入口，而且**会**接管前台，归入前台层。先按四级
规则处置后台候选，再沿用覆盖此动作的已有授权；没有授权时先取得同意。
其他已获授权的键鼠或窗口动作也会改变屏幕，
不能把 reveal 描述成唯一会改变屏幕的工具。归属未能确认（visibility_control=unconfirmed）
时，候选列表里的窗口不是我们启动的，只能用 windows()/see() 继续定位，不要 reveal 一个
不属于本次启动的窗口。

## 虚拟化列表的采集闭环

先在两页上验证“读当前项→滚动/翻页→界面确实变化→读新增项”能工作，
优先用业务 id 去重；没有业务 id 时说明使用哪些内容字段，不按屏幕坐标去重。
记录访问页数、唯一条目数、滚动位置/边界与完整性依据。已知目标为 5000 人而只拿到
80 人时，即使这些数据准确也只是 partial；不能拿屏幕可见行数冒充总数。

出现一次不变化、循环页、权限缺失或工具不足时，停止重复当前无进展循环并保存
partial，不把它解释为所有分页/采集方式都失败，更不能立刻结束完整名单任务。
先核对目标容器、provider 状态、滚动位置与实际项目变化；“像素不变”“调用返回成功”
和“已到列表末尾”是不同证据。继续按路线台账核对有依据的其他分页/展开/搜索，
Text/Selection 读取、ItemContainer/VirtualizedItem，以及导出/API 等方向。
搜索只有能说明查询分区覆盖范围并去重时才支持全量证明；Text/Selection 也可能
只含可见或已选项目，不能仅凭存在该 pattern 推断取得全量。需要改变状态的搜索、
展开、翻页或 Realize 仍按权限契约执行，不能因目标是“读取名单”就视为纯读取。

完整性证据应能说明目标范围、总量来源、已访问的页/分区和终止边界，例如可信业务
总数与唯一条目数一致、分页遍历到有依据的末页，或完整导出/API 的总数/游标终止。
结果截断、列表动态增删或总数口径不明时注明影响。仍无可靠证据则继续适用且获授权
的替代路线；确实受阻时报告不完整、已试到哪里及所需条件，不宣称收全。

## 已知但未试的方向：保留为假设

- 滚轮/ScrollPattern 在 QQ 路线失败后，可对照 --disable-gpu/软件渲染；
  尚未证明会使滚动生效，可能影响性能与显示，变更前评估并取得所需授权。
- 对照 --disable-features 的其他组合，包括 GPU 合成相关方向；原记录没有可靠的
  具体 feature 名，先查当前应用/运行时文档，不编造参数，也不一次改多项。
- 后台读树异常时，与不带 --force-renderer-accessibility 的裸启动作对照；
  这是验证假设，不是建议默认关闭无障碍；新实例条件、前后台及预算保持一致。

每个实验只改变一个条件，先记录基线、预期观测和回退方式；试完更新 memory，
把结果标为已验证/本环境失败/仍未试，不能把清单从文档删掉就当处理完成。

## ItemContainer 专用查询：find_items

`find_items(hwnd,target="",property_id=0,value=null,start_index=0,max_items=100,timeout_ms=8000)`
在同一 worker 调用内持有 NULL 起点及后续元素引用，返回普通元数据；不调用
Realize、滚动、选择或焦点操作，也不接收客户端 COM/Control 引用。它没有
allow_foreground 参数；保留实际前台/鼠标观测，不能把“工具只读”写成 provider
已经被证明永不夺焦。现场工具未注册时记录版本差异，不编造调用。

- `target:""` 直接查询该 HWND 根控件；非空字符串或 selector 在当前完整树中
  精确唯一定位。只有已证实属于目标的独立内容/child HWND 才能用根直读。
- `property_id:0` 必须配 `value:null`，枚举 provider 的项目序列；正 property_id
  允许 bool、int32、有限 float 或最多 6000 字符的字符串。所有整数参数严格排除
  bool/字符串数字；property_id 为 0..2147483647，start_index 为 0..10000，
  max_items 为 1..100，timeout_ms 为 1..30000。正属性不接受 null 或容器。
- 可按实际 provider 能力尝试 Name=30005、AutomationId=30011、IsSelected=30079
  等过滤；不支持属性会报 provider error，不能据此声称容器没有项目。
- `start_index` 是**匹配序列**的偏移。每页从 NULL 重扫，跳过此前匹配项，再返回
  最多 max_items 项及一次前瞻；后页不是上页 COM 引用的延续，也不是稳定快照。
  记录 provider_calls 和定位+查询+验证总成本，不能漏掉反复扫描前缀的时间。
  跳过的前缀不会交付给客户端；首100项加末3项仍只取得103项，不能把已经扫描到
  末尾当成拿到了中间记录。逐页检查实际 items[].index 范围、间隙和唯一业务项数。
- 检查 items、returned_count、read_errors、metadata_complete、result_truncated、
  has_more、next_start_index、reached_end、complete 与 snapshot。每项有 index、
  runtime_id、name、automation_id、control_type、is_offscreen；此处 control_type
  是 UIA 数字类型 id，不能直接当成 see 中的字符串 selector 类型值。
- 正常后页按 next_start_index 推进，但需选择重叠页/重复只读查询核对稳定性；
  列表会动态变化，UIA 也不保证返回顺序。provider 可能跳过数据相等的业务项，
  相同名称应保留，不能只按 name/显示文本去重。runtime_id 只用于本次枚举的元素
  身份/循环证据；虚拟 peer 重建时，同一业务项的值可能跨调用改变，不能充当跨页
  稳定键、业务主键或可持久复用的元素句柄。
  AutomationId 只有经验证非空、在目标范围唯一且确实代表稳定业务身份时才可作
  跨页键；模板复用值、行位置编号或 provider 临时标识不能默认当成业务主键。
- snapshot 始终 false。complete 仅表示从偏移0查询、provider明确返回NULL终点、
  且元数据无错误/截断的这次查询序列；它不承诺该序列等于业务全量。后页即使
  reached_end=true，complete 仍 false；拼接多页也不会自动变成快照或全量证明。
  要声称完整，另核对可信业务总数、分区/边界和重叠页一致性；不能只用末页结束。
- 元数据出错时保留该项 read_errors，metadata_complete=false；超出总文本预算6000
  字符时 result_truncated=true，按 next_start_index 重新读该项，缩小页大小
  或另查字段来源。next_start_index 不前进时停止重复当前无进展查询，保留 partial，
  继续其他适用方向。循环元素、provider错误或预算耗尽也保留部分结果和具体原因。
  先区分任务必需字段和附加元数据：例如名单 name/id 已读而 IsOffscreen 报错时，
  保留已读名单和该错误，分别报告业务字段覆盖与附加元数据缺失。不能丢弃已读
  名单、自动 Realize/滚动补字段或反复重试同一失败 getter；complete 仍按工具原值。
- worker卡死超时仍为 execution_state=unknown；不把它解释成应用没有容器或
  自动重放先前副作用。这里的只读重查由调用方依现场状态决定；其他动作仍遵守
  queued/unknown 的既有核对规则。

示例 HWND 和容器 selector 必须换成现场已核对值；示例不表示真实应用已验证：

| 目的 | find_items 参数 JSON |
|---|---|
| 首批未过滤项目 | `{"hwnd":123456,"target":{"automation_id":"members"},"property_id":0,"value":null,"start_index":0,"max_items":100,"timeout_ms":8000}` |
| 重叠页检查 | `{"hwnd":123456,"target":{"automation_id":"members"},"property_id":0,"value":null,"start_index":90,"max_items":100,"timeout_ms":8000}` |
| 名称属性过滤 | `{"hwnd":123456,"target":{"automation_id":"members"},"property_id":30005,"value":"Alice","start_index":0,"max_items":20,"timeout_ms":8000}` |

## 通用入口：什么时候用 invoke_pattern 与 post_message

固定工具（click/type_text/key/scroll）是常见操作的默认入口。需要只读探测、扩展能力或
比较完整调用成本时，主动检查 invoke_pattern/post_message；即便已有方法可用，也要
核对有根据、适用且可能更高效的通用查询候选。通用入口仍遵守各自权限和数据契约，
不能用它们绕开权限或退回盲点。
所有入口先按四级顺序筛选；后台调用前的防抢焦要求不因换入口而放宽。

**invoke_pattern(hwnd, pattern, target, method, args)** —— 读或调用 provider 暴露的
任意已封装 pattern 成员：
- 用于 Value/Text/Selection/ExpandCollapse/Scroll 之外的成员，或需要读公共属性链，
  例如 `DocumentRange.GetText`、`GetSelection`、`GetVisibleRanges`、`IsSelected`。
- 只读成员表内的成员可在后台查询；表外成员（含 SetValue、Invoke、Close、SetFocus
  等可能改状态或夺焦的动作）需要先取得 allow_foreground 授权。这里“可查询”仅指
  工具权限契约，仍须先满足本目标的后台保护条件；工具接受调用不证明它不抢焦。
  已证实抢焦的表内 getter 或表外动作无有效保护时均不从后台调用，已有广义前台
  授权只用于之后相应前台层，不能靠 allow_foreground:true 把它当后台再试。
- `args` 列表只接受 bool/int/有限 float/str，不接受列表内的 null、嵌套容器或 Control
  引用。`args:[]` 和整个 `args:null`（Python 的 args=None）都表示不传参数，
  不等于 `args:[null]`；后者会被拒绝。属性/GetSelection 用空参，
  `DocumentRange.GetText` 需一个 1..6001 的整数参数，例如 `args:[4096]`。
- `LegacyIAccessiblePattern.Name`、`Description`、`Value` 和
  `WindowPattern.WindowVisualState` 已加入只读成员表，可按只读接口后台查询。
  这不放开 Legacy 的 DoDefaultAction/Select 或 Window 的状态修改方法，也不改变
  click 的前台权限门。现场工具版本尚无这些成员时记录版本/契约差异，不编造成功调用。
- **不要用 Get 前缀判断安全**：表是显式维护的。某个应用的只读 getter 实测会夺焦时，
  在 memory 里把该路线记成 uses_foreground=true，不要继续当后台方案复用。
  停止该路线的无保护后台调用，继续核对其他合理后台来源，不反复制造抢焦来测量。
  “工具允许只读调用”不等于 provider 已被证明不夺焦；测量时记录前台/鼠标证据，
  未观测副作用时不能宣称已证实后台稳定。
- 历史旧契约曾要求上述 Legacy 属性读取带 allow_foreground；当时同一窗口内 `Name`
  授权后返回字符串、`Description` 返回空串。这些历史返回值保留为旧版本证据，
  不再作为当前读取必须授权的依据，也不证明其他应用/版本的返回内容和副作用。
- 定位是纯精确的：字符串或组合 selector 必须在当前完整树唯一命中，否则
  `no such control` / `ambiguous target` / `tree incomplete`，不动作。
- 返回值已投影成普通数据：TextRange 变成有界文本，Control 变成元数据。
  `possibly_truncated` 提示具体文本/范围触及 API 有界上限，`result_truncated` 是整体
  结果有界化标记；自动 TextRange 投影触及 API 上限也会影响整体标记，两者可以同时
  为 true，不是互斥的两类原因。任一为 true 都不能作为全文完整证据，两者都为 false
  也不证明当前范围已覆盖整个业务列表。遇到
  `result unsupported` 说明该类型还没有投影——调用可能已经执行，不得自动重试，
  记录这个缺口（需要哪种投影）而不是当成失败路线删掉。
- `pattern not wrapped` 表示当前依赖没有该 pattern 的封装，附带的 pattern_id 就是
  后续补封装的目标；这和“应用没有暴露该 pattern”不是一回事，不能混成应用不支持 UIA。
- 通用 args 仍不能表达 Control 引用或列表内 null；这是早期 ItemContainer 无法
  首轮/续项的原因。本轮该容器查询改用专用 `find_items`，NULL 和续项引用只在
  同一 worker 调用内使用，不为 invoke_pattern 开放任意引用传参。返回的 Control
  元数据仍不是可传回的元素句柄。其他方法若需要这种输入，按实际原因保留参数
  适配缺口、已读结果及后续受控引用/失效校验方向；不伪造引用，也不报成应用未暴露。

**post_message(hwnd, msg, ...)** —— 原生窗口消息：
- `msg` 必须是数值整数，如 `13`，不接受 `"WM_GETTEXT"` 等名称字符串。
- 查询状态用 `wait=true`（SendMessageTimeoutW），带 child HWND 和具体消息；
  `WM_GETTEXTLENGTH`、`BM_GETCHECK`、`CB_GETCURSEL`、`LB_GETCURSEL` 是典型查询。
- 异步投递用 `wait=false`（PostMessageW）。响应只有 `queued`，没有 result：
  消息还没到目标，之后仍可能改变窗口。
- 文本走托管路径：`WM_GETTEXT`/`WM_SETTEXT` 由服务分配缓冲区，绝不传指针；
  `WM_SETTEXT` 会在同一时间预算内读回比较，`text readback mismatch` 才算写入不符，
  `readback unavailable`/`budget exhausted` 只说明本次无法验证。
- 广播句柄、`WM_COPYDATA`、`WM_DROPFILES`、同进程窗口一律拒绝；未知标量需要
  allow_unsafe + 前台授权，且调用方须自己确认该消息不携带指针或句柄。
- 权限按**效果**判断，不按消息是否带指针判断：`WM_LBUTTONDOWN/UP`、`WM_MOUSEWHEEL`、
  `WM_KEYDOWN/UP/CHAR`、`BM_CLICK`、`WM_SETTEXT` 和未知标量都需要 allow_foreground；
  只有 `WM_NULL`、`WM_GETTEXTLENGTH`、`BM_GETCHECK`、`CB_GETCURSEL`、`LB_GETCURSEL`
  和托管的 `WM_GETTEXT` 能在后台执行。鼠标消息的参数是 Win32 约定：按钮消息 lparam
  用客户区坐标，滚轮 lparam 用屏幕坐标、wparam 高字是带符号滚动量。截图坐标要先换算。
  上述后台许可仍不是 provider 防抢焦保证；动作消息即使已获授权也先按四级顺序
  与调用前保护执行。queued 消息的保护和观测不能只覆盖入队瞬间后立即撤销。

## 调用小抄：数值 msg 与明确 args

下面是工具参数 JSON，可直接按相应工具调用；先把示例 `123456` 替换为当前已核对的
内容窗口 HWND，把 `123457` 替换为归属明确且 class 匹配的 child HWND。
这些示例不代表该窗口一定暴露对应能力，也不是要求逐条执行的调用脚本。

原生只读查询使用 `post_message`，`wait:true` 才能取同步结果。以下数值已按当前
win32 只读白名单核对；消息名称仅用于理解，实际 `msg` 必须传整数：

| 查询 | post_message 参数 JSON | 检查返回与范围 |
|---|---|---|
| WM_GETTEXT，13 | `{"hwnd":123457,"msg":13,"wait":true,"max_chars":4096,"timeout_ms":1000}` | 读取返回 text；文本受 max_chars 限制，触及上限不能据此称全文完整 |
| WM_GETTEXTLENGTH，14 | `{"hwnd":123457,"msg":14,"wait":true}` | 保存 result，与文本长度/动态变化核对；长度不代表内容已采集 |
| BM_GETCHECK，240 | `{"hwnd":123457,"msg":240,"wait":true}` | 仅用于匹配 Button class 的状态查询，按返回状态值解释 |
| CB_GETCURSEL，327 | `{"hwnd":123457,"msg":327,"wait":true}` | 仅用于 ComboBox 当前选择索引，不是全部选项列表 |
| LB_GETCURSEL，392 | `{"hwnd":123457,"msg":392,"wait":true}` | 仅用于 ListBox 当前选择索引，不是全部项目列表 |

托管 WM_GETTEXT 不传 `wparam/lparam` 指针或自行分配的缓冲区地址；服务处理缓冲区。
不要把一个查询的 child HWND 直接复用于其他 class 的查询，结果为错误/空值时先核对目标。

以下 `invoke_pattern` 示例中的 `target:""` 只适用于根控件确实承载目标属性的情况；
否则替换成现场得到的精确字符串或组合 selector。只读调用显式使用
`allow_foreground:false`；保存返回的前台采样与鼠标观测，未观测的副作用仍记未知。
这些 JSON 只展示参数，不能替代后台调用前保护；仅有前后采样相同不证明中途未抢焦。

| 查询 | invoke_pattern 参数 JSON |
|---|---|
| Value 属性 | `{"hwnd":123456,"pattern":"ValuePattern","target":"","method":"Value","args":[],"allow_foreground":false}` |
| 有界正文 | `{"hwnd":123456,"pattern":"TextPattern","target":"","method":"DocumentRange.GetText","args":[4096],"allow_foreground":false}` |
| Legacy 名称 | `{"hwnd":123456,"pattern":"LegacyIAccessiblePattern","target":"","method":"Name","args":[],"allow_foreground":false}` |
| 当前选择 | `{"hwnd":123456,"pattern":"SelectionPattern","target":"","method":"GetSelection","args":[],"allow_foreground":false}` |
| 表格行数 | `{"hwnd":123456,"pattern":"GridPattern","target":"","method":"RowCount","args":[],"allow_foreground":false}` |
| 表格列数 | `{"hwnd":123456,"pattern":"GridPattern","target":"","method":"ColumnCount","args":[],"allow_foreground":false}` |
| 窗口显示状态 | `{"hwnd":123456,"pattern":"WindowPattern","target":"","method":"WindowVisualState","args":[],"allow_foreground":false}` |

Legacy 的 `Description`/`Value` 读取沿用 Name 示例，只替换 method，并保留 `args:[]`。
Text 的 maxLength 是有界读取长度，不是分页游标；满 4096、API/整体截断标记或
业务范围只覆盖局部时都不能声称全文/全量。GetSelection 返回当前选择及其投影范围，
不能把空参数改成 `args:[null]`，也不能拿返回的 Control 元数据当引用传回。

已经明确获准调用 Grid.GetItem、且确认行列范围时，可用下面参数读取第 0 行第 0 列：

```json
{"hwnd":123456,"pattern":"GridPattern","target":"","method":"GetItem","args":[0,0],"allow_foreground":true}
```

这条调用的两个整数参数当前已可表达，成员本身未列入默认只读表，因此需沿用已有
授权，不能当作无授权后台示例；若从后台执行还须先有已验证有效的保护，否则放入
后续前台层候选。返回的单元格 Control 元数据仍需核对内容与投影能力；
未取得全部单元格时，行列计数和单个 GetItem 成功都不是全表采集证明。

## 效果验证、超时与知识回写
查询保存真实 result/text；写入用读回；点击用目标状态/反馈；滚动用位置和项目变化。
call_completed、queued、returned 都不自动代表业务完成；provider 返回 False 时
按具体方法语义处理。worker 或消息超时为 execution_state=unknown，先读目标现状，
不自动重发可能已执行的动作；busy/not_started 才能按明确未执行处理。
queued 或 unknown 后，先用不重复副作用的读取检查计数、值、选择或业务状态，必要时
观察状态是否仍在变化；一次空树或计数暂未变化不能证明动作未执行。结果尚未查清时，
不通过另一工具/另一条路线重放同一点击、提交、翻页或写入，也不并发提交替代动作。
若树读失败，继续独立的只读状态通道和 provider/窗口调查；查不清则保留“执行结果未知”，
说明具体未验证部分。确证未执行或能安全处理已执行状态后，才决定下一业务步骤，
不能因为想比较路线效率而重复不可安全重放的副作用。

用 remember 写 Markdown body，必须包含下列八个二级标题；安装后无需额外交接文件：
- `## 目标`：任务、全量/局部范围、可观测完成标准、已获授权的副作用及成本要求。
- `## 环境与适用条件`：日期、实际版本及来源、exe、启动参数、窗口前后台/可见状态、
  DeskWeft/依赖版本；缺失字段写未记录，不补猜。
- `## 已验证步骤`：逐步工具、实际参数、返回值、效果验证与光标/前台副作用。
  后台步骤另写调用前保护与观测范围；发生过抢焦的步骤不能因事后恢复改记为后台。
- `## 已尝试但失败`：输入、观测/错误、环境、失败范围；一次失败不推广到所有版本。
- `## 实测记录`：候选路线台账，计数/覆盖率、定位+调用+验证耗时、调用/全树次数、
  前台/鼠标证据、像素变化的原值、样本/统计口径及日志/截图位置；历史转录与本次新测
  分开，冲突数据并列。没有测量的指标写未测，不补造性能或后台稳定性结论。
  每条另记四级归属、同层完整成本/比较口径、调用前保护、异步观测范围和降级理由；
  只有端点相同写端点证据，不能写“全程未变”。
- `## 未解决`：能力缺口、影响的目标、已试到哪里、下一步需要什么；区分任务尚未完成、
  单条路线失败和动作执行结果未知，保留 Control 引用传参等工具后续工作。
- `## 未试方向`：标未验证，写思路依据、对照步骤、预期观测、代价与回退；
  权限未满足、工具缺失、已试失败分别记录，并说明本次未试原因；没有内容写尚未记录，
  不能将“尚未记录”等同于不存在其他路线，也不能只登记一个可行低成本方向就不再推进。
- `## 更新记录`：新增、修正、证伪及旧结论的适用范围变化。

覆盖前先读完整旧正文并合并；保留失败与未试路线，不能只写最新的成功结论。
未知副作用填 uses_foreground=true，新方案 rank=0。
已证实抢焦同样填 uses_foreground=true，记录触发条件与恢复；已有实验授权不把它改成
false。受保护的新变体独立记录机制、环境、效果和观测证据，不继承旧路线的后台结论；
只有本条件确实验证后台成立才按证据记录，不能用 rank 或授权替代副作用证据。
版本仍未知时传 version=None，
记录为 app@unversioned，明确告知用户尚未归属实际版本，不丢弃本次探索报告。
未定版本记录不得升为 reviewed/proven；确认实际版本后另建本版本记录再验证。
用户明确确认 key/id 与内容后再 approve(expected_revision=原摘要)；有多次成功记录
并取得确认后再 confirm_proven。stale plan 重新读取确认，不悄悄刷新摘要继续审核。

## QQ 搜索与导航的反例：不要推广单次成功或表面保护

以下是 2026-11-08 本轮样本的适用边界，不是所有 QQ/控件/版本的保证：

- 旧的含 name selector 在写后短暂返回 no such control；之后重新读取完整树，通过
  唯一 ComboBoxControl 完成恢复。本样本未直接证明 Name 永久变成所写文本；名称
  可能动态或定位时序发生变化，不能依赖未经复核的旧 Name。重新读取当下元数据，
  核验目标身份和稳定语义条件；只有当前完整树确实唯一时才能用该类型定位，不能
  取第一个 Edit/ComboBox，也不能把“找到另一个框”当作原目标读回或恢复证明。
- 某次 ValuePattern.SetValue 返回成功且读回相等，但 foreground_changed=true。
  效果正确和满足后台目标是两件事；该环境中的路线按前台副作用记录，不能因已有
  广义前台实验授权或随后恢复原值，就继续把它当无保护后台候选调用。
- 保护尝试中，后台调用 LockSetForegroundWindow 返回 false、error=5，表示没有取得
  该保护。禁用 QQ 当时已知的可见顶层后，仍由 enabled 的 child renderer 先进入
  前台，随后父窗口成为前台；setter 报 UIA_E_ELEMENTNOTENABLED，值没有改变，
  原 enabled 状态已经恢复。因此本次既未获得合格后台保护，也未完成写入；不能
  把报错/窗口禁用当作“动作没发生任何可见副作用”。禁用顶层、WS_EX_NOACTIVATE
  或事后抢回均不能直接给出防抢焦承诺，其他保护/隔离方案须实际实现并验证，
  没有实现的能力继续写工具缺口。
- Legacy.DoDefaultAction 的无固定等待变体在本次导航样本中仍观察到页面切换，
  可以作为减少固定等待的候选；它不证明任意 Legacy 动作都会生效或全程不抢焦。
  方法调用的 effect_verified=false 不能替代后续业务标志验证；定位、验证和清理仍
  要计入完整成本，单次端点相同或局部耗时下降不能升级为后台稳定性/性能保证。

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
````
以上代码块为SKILL.md完整快照；分发时须包含整个`skills/windows-app-automation/`目录中的references与scripts，不能只复制入口文件。正文模板和必要历史起点已内嵌，不依赖未随安装分发的交接稿。skill保留跨应用探索方法、分支与已知实验方向；某软件某版本的实际结果归memory。完整原始转录和来源边界在仓库设计稿§7，供审阅追溯，不是安装后运行的必需依赖。静态skill携带的起始假设不得升级为已证实方案，不自动把历史条目种成rank>=2的记忆。

### 6.2 skill 源码与分发的历史现场记录

源码唯一位置为 `skills/windows-app-automation/SKILL.md`。原交接稿记录：DSH 的 `~/.dsh/skills/` 为实体目录；Codex 的一个现有 relay-imagegen skill 使用指向 `C:\Users\32677\source\relay-imagegen` 的 Junction；Claude 的 `~/.claude/skills/` 为实体复制。它们是原稿现场状态，**本次未重新核验**，不能推断三个客户端机制相同。

实施部署时先读当前目标目录/链接目标，再选择复制或链接到本仓库 skill 源码目录；复制方式必须同步更新，链接方式核验目标存在。以客户端重新加载后的实际发现结果为准。不要为了套用历史示例覆盖已有目录，也不要把运行时包副本当成 skill 唯一源。文档编辑本身不操作用户全局skill目录；本次改名的实际客户端与完整skill同步验收另见§0.1。

### 6.3 私有 desktop 的观察与接管边界

当前随包入口提供JSON阶段、真实worker与窗口归属、字段效果摘要、输入desktop/前台事件和清理结果，不包含实时画面面板、远程桌面或人工接管工具。现有see/PrintWindow具有按HWND取图的实现，但本轮随包runner丢弃图像并仅保存脱敏统计；没有单独验收私有desktop下图像非空、正确与实时，不能把“调用过see”写成画面预览已实现。

可研究的只读预览是：在保持隔离的执行环境中取得目标窗口图像，再把图像交给当前用户桌面的查看器。捕获、传输、展示分别验证应用渲染支持、隐私、资源/超时和完整成本；取得黑图或旧帧时保留限制，不能靠切换desktop补图后仍称后台。此处只定义候选方向，不增加工具名、界面或已实现承诺。

显式SwitchDesktop会改变接收用户输入的desktop，可作为另行实现的查看/接管方向；它会占用当前输入环境，也使原先非输入desktop前提失效。当前helper不调用它，并在本轮结束后结束Job成员、核对活动归零、释放自有desktop句柄，不保留可随时接管的长期会话。将来若需要接管，须先停止新增自动化、查清已发动作/恢复责任并明确进入前台层，再单独验收切入/切回和异常退出；不能把这次实验描述为已经具备该能力。

“应用内部可以激活”不意味着全部前台操作都自动转为后台。当前只证实本报告中的QQ语义读写等具体路径可以留在私有desktop完成；原生消息、其他UIA模式、渲染或业务状态分别验证。SendInput和真实鼠标/键盘没有按目标HWND隔离的承诺，现有key工具仍有前台与屏幕条件；登录安全desktop、UAC或其他session也不在本次验收内。路线分类以用户输入desktop是否被接管和已验路径为依据，不因换desktop便默认所有操作可用。

另建Windows交互会话或虚拟机只列为更重的候选，尚未实现或验收；其输入、渲染、权限与资源条件需另行验证。

## 7. 实施顺序与部署

以下 1–7 保留基础三层实现的完整实施与部署次序，不能因本轮只修补缺口而删除其能力。基础实现已存在；本轮增量按后面的专门复核次序完成，不把旧现场记录当作新验证。

1. 完成 memory、严格 schema、未定版本记录、正文续读、revision 与临时目录行为测试。
2. 完成 app_info；实现 post_message 的同步标量、异步投递、托管 GET/SETTEXT 和同预算读回。先用 mock 验证参数、错误与指针宽度，不接触真实用户窗口。
3. 完成 tree 的诊断入口/原生句柄、pattern 守卫、invoke_pattern 的属性链/投影；修正现有动作的歧义、中心点击、文本验证、滚动枚举、激活检查及启动窗口归属。测试所有拒绝分支在发送动作前发生。
4. 完成 worker 的 spawn/握手、非阻塞帧、deadline、busy、异常回收、重建及 close。纯 IPC 测试使用测试模块的假 worker，不需要真正 UIA；再验证实际 MCP 包装全部经过 worker。
5. 注册基础 7 个工具及本轮 find_items，核对 16 项工具的 schemas/HTTP 请求和生命周期；以 FastMCP lifespan 的 finally 调 uia_worker.close，确保停止服务会回收本服务 worker。加入完整独立 skill，更新 README/INSTRUCTIONS，删除过度诊断、默认后台 Legacy、所有 UIA 必夺焦和“用户离开就可执行”等失实描述。后续按 §2.6.1 增补 `forget`，工具数为 17，需同时核对新工具的 schema、拒绝分支与真实 MCP 调用。
6. **核验 check.py 测试清理**：当前实现已按本次启动PID、已记录HWND和`_close_owned`核对归属后清理，不再无条件关闭所有Notepad窗口。继续要求句柄/PID归属成立；无法确认单实例或broker窗口归属时，跳过相关应用用例并报告。本次改名未运行GUI自检，源码检查不代替真实清理与效果验收。
7. 在隔离桌面或确认安全的会话运行 GUI 集成回归；最后才按已授权范围部署。

本轮增量复核次序：

1. 在共享 target 校验/resolver 增加 selector，并先用假当前树覆盖 AND 消歧、字段不可读、矩形变化与零动作拒绝；四个调用方复用规则，旧字符串测试继续通过。
2. server 的四个 target schema 使用严格 JSON 类型并禁止未知字段；核对真实 MCP 的错类型拒绝，以及普通 dict 经包装和 worker 固定分派原样进入内部入口。worker 协议不需要改写。
3. 从已安装 windows-mcp 0.8.8 的真实 wrapper 逐项核验 §4.3 表；假 provider 验证新增只读值保留原类型且不需前台授权，写/未知方法在访问 provider 前拒绝。未知 Get 前缀不能自动获准。
4. 同步实际 SKILL.md 与 §6.1 的完整内嵌正文，场景核对“已有可用路线但任务未完”“一次不滚”“候选缺权限但另有只读方向”“已 queued/unknown”。路线库须有具体操作和验证，不能只增加禁止提前结束的口号。
5. 运行相关和既有单元/MCP/worker 测试，记录实际命令与结果；文档不预填断言数、耗时或现场效果。部署、服务重启与真实 GUI 测量按当前授权单独执行；未执行的验收明确保留。find_items 的真实 provider、分页和 metadata 边界按 §4.7 与独立报告核对；其他任意 Control 输入仍列为已知缺口。

推荐验证命令（仓库根目录，venv 路径按实际安装调整）：

```powershell
$taskPython = "$env:LOCALAPPDATA\deskweft\.venv\Scripts\python.exe"
& $taskPython -m unittest discover -s tests -v
# 仅在隔离桌面或已授权交互会话运行；本次改名未运行此GUI自检：
& $taskPython -m deskweft.check
```

editable 安装和运行目录不是两个代码真相。**不要再 Copy-Item 整个包“保险同步”**。部署前先核对任务配置与 import 来源：

```powershell
Get-ScheduledTask -TaskName deskweft-helper | Select-Object -ExpandProperty Actions
Push-Location "$env:LOCALAPPDATA\deskweft"
try {
    & $taskPython -c 'import deskweft.server; print(deskweft.server.__file__)'
    & $taskPython -m pip show deskweft
} finally {
    Pop-Location
}
```

若导入不指向工作仓库，先检查实际导入路径和任务工作目录中的`deskweft/`，并检查是否仍有旧`winmcp/`安装或任务。备份该副本后调整任务工作目录至仓库，或移走已确认过时的副本；只重新安装 editable 不能消除当前目录的遮蔽。随后在目标 venv 安装该仓库及声明依赖，并从实际任务工作目录复核导入路径。

#### 7.0.1 部署目录不得持有代码副本（2026-11-09 实测）

改名后的部署目录曾同时存在**两份**非仓库代码，两者都会让"改代码→重启服务"看起来无效：

| 位置 | 来源 | 后果 |
|---|---|---|
| `%LOCALAPPDATA%\deskweft\deskweft\` | 从仓库复制 | cwd 优先，遮蔽 editable 安装 |
| `%LOCALAPPDATA%\deskweft\.venv\Lib\site-packages\deskweft\` | 从 wheel 安装的快照 | 即使 cwd 干净，导入仍是旧代码 |

实测表现：仓库已注册第 17 个工具 `forget`，重启服务后 `tools/list` 仍只有 16 个，且
`server.py`/`memory.py` 与仓库逐文件比对不一致。清 `__pycache__` 无效，因为解释器
从未读取仓库文件。

处理（已完成）：两份副本移走（`deskweft.copysnapshot-*`，未删除）；对部署 venv 执行
`uv pip install --python <部署venv> -e <仓库>`，改由 editable 指向仓库；重启后导入路径为
`C:\...\source\winmcp\deskweft\__init__.py`，17 工具在线。

**规则**：部署目录只放脚本、日志、venv 与 skills；`deskweft/` 包只能由 editable 安装
指向仓库提供。改代码后只需重启服务，不需要同步任何副本。若再次出现"改了没生效"，
按 `direct_url.json` 是否 `"editable": true`、`import deskweft; deskweft.__file__`
是否落在仓库、以及 `site-packages` 是否存在实体 `deskweft/` 三项依次核对。

当前`install.ps1`在交互登录会话注册`deskweft-helper`，任务动作是隐藏的`pwsh.exe -File run-helper.ps1`；runner再隐藏启动本目录venv的`python.exe -m deskweft.server`，将标准输出/错误分别写入`helper.out.log`和`helper.err.log`。安装器最多轮询30秒、间隔250ms，要求8765只有一个127.0.0.1监听，并核对owning PID的命令行属于本安装venv和`deskweft.server`；异常监听或超时返回错误，任务已注册不等于服务已就绪。runner另有的10秒日志状态采样不是MCP握手验收。

改代码/依赖后需重启实际监听服务；同时检查 python.exe 和 pythonw.exe，仅停止确认属于该服务的 PID。用任务状态、8765 端口的拥有 PID、MCP 初始化与工具清单一起判断启动成功，不能只看端口计数。不要在交接脚本里自动 push、点击凭据账户或写本机代理。

### 7.1 历史操作诊断必须保留，但不能变成自动动作

以下历史记录来自基线交接稿§8.2/§8.3、设计稿和README；改名前的审阅阶段未重新启动任务、操作凭据窗口、测量代理或更改ACL。改名后的服务启动与验收另记于§0.1，表内当前脚本行为按现有实现核对，不替代GUI现场复测。

| 触发或观测 | 历史事实、现有边界与下一步 |
|---|---|
| 启动命令报 4294967295 | 原稿记录 `Windows Job runner exited with exit code 4294967295` 时任务可能已启动。分别只读检查实际任务 Action/状态、8765 的 owning PID、进程命令行及 MCP 握手，不因工具层退出码就重复启动。 |
| Git 操作停滞 | 历史凭据窗口为 `Select an account`、`Avalonia-*`，标题无 git，PID 与 Git 不同；原稿称遇到三次。windows/see 可辅助确认，但不按旧坐标或自动选首个账户，须核对本任务所用账户与已有授权。同步修正当前 INSTRUCTIONS 直接建议点账户的文案。 |
| 网络/代理异常 | 原稿记录 Git 代理 `127.0.0.1:7890`，7897 当时不可用；这是历史值。读取当前配置及来源、相关环境变量与监听状态，区分代理故障与认证等待；不自动改全局配置。 |
| 无控制台或无日志 | 当前install.ps1注册交互会话的隐藏pwsh.exe任务，由run-helper.ps1隐藏启动venv的python.exe并重定向helper.out.log/helper.err.log；安装器以最多30秒轮询及监听进程命令行核对判断启动。仍须检查实际任务Action、日志、监听归属和MCP握手；服务需在有目标窗口的用户会话内。 |
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
| 版本证据链 | 六级顺序可逐级 mock：任一级返回即停且 `source` 正确；`sole_candidate` 必须带 warning；候选多于一个时必须落到下一级而非乱选 |
| 版本实测对照 | 对运行中的 QQ 断言 `source == "child_cmdline"` 且 `version == "9.9.22"`；对 Edge 断言 `source == "file_version"` 或 `sibling_dir"` 且版本以 `157.` 开头（两个应用必须走不同级） |
| 正则 | `\d+(?:\.\d+)+(?:-\d+)?` 命中 `9.9.22-40824`；短正则 `\d+(?:\.\d+)+` 命中不了（写成断言防回退） |
| 目录 | 版本名但非目录、setting.json、多个版本均不误判；验证 9.9.9/9.9.22/10.0.0 不做字符串最大值推断 |
| 记录/schema | 临时目录读写 round-trip；中文 app、`../`、保留名均不越过根目录或碰撞；路径摘要与内容 key 互相校验；坏 YAML/日期被解析成对象/错误 bool/未知 schema/重复 id 拒绝覆盖 |
| 未定版本 | version=None 保存到 app@unversioned 且可 recall；字符串 unversioned 不冒充版本；有效 rank=0，存储真信任位拒绝；approve/confirm_proven 的 true 返回 version unconfirmed；后续实际版本另存，旧观察保留 |
| 匹配 | 精确 key、同 app 回退不混入 QQMusic、Windows 路径、exe stem、子串、空 query、未命中成功；unversioned 只精确读本记录、不家族回退 |
| 预算/续读 | 全响应 body+unresolved.text 不超预算；被截断计划有 next_body_offset，按稳定 revision 续读可恢复完整正文；中途内容变化不得拼接；非法 offset/非精确 key 续读拒绝；offset==长度可正确结束 |
| 排序/信任 | 全部四组合得到 3/2/1/0；同分稳定；修改 body 后清零；审核两位独立更新和撤销；旧 revision 的审核不能给并发覆盖后的内容置位 |
| 并发/失败 | 两线程同时追加不同 plan，两条都保留；mock os.replace 抛错，旧记录仍可读；冲突不改旧正文 |
| 继承 | key 引用、只跟随一次；缺失/自引用/链式引用报错；有效 rank=0；显式 materialize 后与源独立 |
| 缺口 | 由 remember 的真实 body 读出 plan_id 与文本；删段落再覆盖后消失；长未解决段落不能绕过总预算 |
| 删除 | 单条删除后其余 plan 与原记录保留；删掉最后一条时记录文件一并消失且 recall 不再列出该 key；旧 revision 返回 `stale plan` 且不删任何内容；空 plan_id 缺 `confirm` 拒绝且不写盘；继承记录、损坏记录、缺失 key/plan 分别返回 `inherited record`/`invalid record`/`plan not found` 并保留原文件；写盘失败保留旧记录；其他版本与其他应用不受影响；无 `.tmp` 残留 |
| UIA 授权 | 只读白名单在 allow_foreground=false 时可查询；写/未知成员拒绝且 provider 调用为零；不能按 Get 前缀放行、不能读取原始 Element/pattern/textRange 字段或执行表达式 |
| 本轮只读扩展 | §4.3 常量逐项与代码相同；用真实 wrapper+假 COM 验证新增 scalar getter、Legacy GetSelection 的真实类型与投影；至少直接验证 Legacy Name/Description/Value 和 WindowVisualState 无授权可读；DoDefaultAction/Select/SetValue/SetWindowVisualState/未知 Get 方法在任何 provider 获取前拒绝；不以属性 getter 的放行证明真实 provider 无夺焦 |
| UIA 定位/诊断 | 根目标、唯一 AutomationId/name、重复/未命中/不完整树分别覆盖；诊断 warning 保留获取/遍历错误，吞错的 None 标 cause_unknown；大小写、数字 GetPattern 回退、SelectionPattern2 缺 constructor、无 getter、getter抛错均可解释 |
| 本轮 selector schema | 五个工具同时接受原字符串及严格 selector；拒绝空对象/仅rect/全空身份/未知字段/nth/index/contains/null/bool HWND/非正 HWND/数值字段中的字符串数字/错长度或类型 rect/非正宽高；name="123"仍合法；真实 MCP 证明拒绝时内部动作未被执行，内部直调也拒绝，框架不先转换类型 |
| 本轮 selector 定位 | 同名+重复 id 用 control_type/rect/native_hwnd AND 唯一消歧；所有谓词大小写敏感；明确空字符串谓词不被丢掉；匿名且七pattern空节点仍返回，filtered_anonymous=0，两个同类匿名节点不能误报唯一；无项/多项/矩形已变/元素消失返回对应拒绝，消息与真实输入计数为零；任何所需字段不可读必须 tree incomplete，不能默认为不匹配后误选另一项；未请求的可选字段错误保留诊断 |
| 本轮 selector 路由 | 结构化 click/type 必须先匹配全部字段，再核验真实 UIA native HWND、当前原生 child 和允许类，后台消息才可发送；任意外部/陈旧 HWND 或其余条件不符不发消息；无可用 native child 时保留 UIA 授权门；scroll/invoke 同样遵守原权限；五条 worker 分派收到的 dict 与输入相同，无 COM 缓存；invoke 根仅显式 target=""，{} 不变根 |
| UIA 返回值 | Value属性、DocumentRange.GetText、TextRange列表、Control列表、合法False查询、动作False；未知对象返回 result unsupported 且不重放；总字符/条目/深度预算与 API possibly_truncated 分开；4096上限返回4096单位也不得标全文 |
| Control 输入与专用适配 | 通用args继续拒绝列表内null和Control字典；find_items在同一worker调用托管NULL首轮与元素续项，原始引用不进协议/缓存；其他任意Control输入仍报具体缺口，不报成应用未暴露 |
| find_items 参数/定位 | tools/list含第16项与§4.7签名；严格范围/property_id0配null/正id值类型/有限数/字符串长度均校验；schema和内部拒绝时provider零调用；根、唯一精确字符串/selector、歧义、未匹配、不完整树与缺pattern诊断均覆盖 |
| find_items 枚举/分页 | NULL起点和原始COM续项仅同调用；start_index跳过匹配序列而非原始业务下标；每页从头重扫并前瞻，has_more/next/provider_calls准确；同名不同元素保留；重复身份、RuntimeId缺失/恢复的混合路径循环均有界拒绝，不存跨调用COM或把RuntimeId当稳定业务键 |
| find_items 元数据/完整性 | 字段读取异常保留其他字段与read_errors/metadata_complete=false；6000总字符预算截断重读当前项；control_type返回数字id不冒充selector字符串；仅首偏移0+明确NULL末尾+无错误/截断才complete，suffix reached_end不证明全量，snapshot恒false；相等数据可能被provider跳过，业务全量需独立总数和重叠验证 |
| find_items 失败/live | provider异常/循环/期限保留部分结果及complete=false；阻塞COM由worker回收，unknown不自动重放；真实WPF已知总量+虚拟化+同名+远端属性+重叠页+超时恢复及Explorer独立文件集核对单独显式执行，前台与字段失败照实记录；测试报告不推广为所有provider都完整 |
| 本轮前台采样 | mock worker 返回真实 before≠after时server不覆盖，并据其原值保留foreground_changed；worker缺失采样的失败在整次worker call前后采样，证明一次真实变化不会因动作后重采而变false；see成功样本在meta中不被包装丢掉；仍说明两点采样不证明中途从未夺焦 |
| UIA 线程/进程 | 至少一个实际 HTTP MCP 请求在 worker 主线程完成定位→pattern→调用→投影；父端无COM对象，初始化/退出配对；同步工具线程池不得绕过worker直调 |
| worker 生命周期 | 首次transport_ready/ready顺序与共用握手deadline；初始化失败不发送动作；busy不排队且not_started；执行超时/崩溃只失败一次，不重放，确认旧进程退出后可重建；transport未完成或进程未回收则sticky unavailable；stopping关闭不并发碰连接 |
| IPC/deadline | 假worker半个帧头/半个正文后停住、发送背压、EOF、错误request_id、坏JSON、超限长度均有界失败并回收；图片超限略图仍保留树；metadata超限不得截坏帧；重复超时不积累进程或应用收发线程 |
| 原有动作 | 原生匹配重名不发消息；命名目标缺失/模糊多义/树不完整时不激活、不动光标、不点窗口中心；空click无唯一原生目标返回target required；无效矩形拒绝；真实键鼠前可见/非最小化/焦点校验；快捷键规范化保留；已调用后的异常/False/不可读不悄悄换另一条写路径；Value=None与缺pattern不假报已验证或确定失败；滚动使用NoAmount与正确的上下枚举，False/位置不变可解释 |
| 启动归属 | 直接进程/已证实子孙的全新窗口才可隐藏；不相关窗口零隐藏/激活调用；baseline含隐藏窗口；单实例/broker/权限失败/PID或HWND复用不误认；原字段兼容，unknown/applied/partial报告与实际证据一致 |
| 消息校验/权限 | 无效/广播/本服务PID同步hwnd、bool/越界参数、错误控件类拒绝；未知标量要unsafe和前台授权；未托管COPYDATA/DROPFILES即使unsafe也拒绝，托管GET/SET走专门分支；异步查询拒绝 |
| 消息结果 | 异步成功仅queued无result；同步成功returned有指针宽有符号result；0/-1查询合法；API失败LastError=1460/其他/0可区分，不杜撰超时；超时execution_state=unknown且不重发；前台字段每个分支都存在 |
| 托管文本 | 中文/emoji/空串/NUL/孤立代理输入、容量边界、读回修复；GETTEXT空串与可能截断；SETTEXT错误返回、完整匹配/不符/验证不可读/预算耗尽；超过4096的长文本写入不得被预览截断误判失败；内部缓冲按UTF16单位分配，不读取超时残片，不将Static图像当文本 |
| GUI 回归 | 自建跨进程窗口上验证现有工具、同步文本/状态、ExpandCollapsePattern 等能力；检查实际效果、光标/前台；清理只触及本轮PID/HWND；不固定QQ节点数或延迟 |
| MCP/文档/skill | tools/list 共16项，基础7项与find_items签名一致；真实请求的bool→int、字符串→授权等强制转换被拒绝；错误结构、权限docstring、独立skill模板和路线一致；未知版本观察可写而不能升级信任；skill包含原生/UIA/Electron/UWP/自绘/虚拟列表/外部接口及未试方向；历史数字不当新测结果 |
| 本轮 skill 完成门槛 | SKILL与§6.1内嵌全文一致；高rank基线先分类仍服从四级；在同层、同任务范围比较保护/准备+定位+worker/调用+等待+验证+撤销/恢复总成本，冷暖/一次性摊销分别列；已发现/适用且可安全继续的候选实际验证，其余有可核实未试/降级理由；一次不滚只停该循环，继续相关分页/搜索/Text/Selection/ItemContainer/导出/API；部分名单无完整证据不能称完成；queued/unknown不借换路线重放副作用；不得编造预算、要求穷举或自动重启 |
| 四级顺序与授权压力场景 | 后台高效→后台低效→前台高效→前台低效；前台更快、历史基线、高rank或广义前台实验授权均不能跳过合理可行后台候选；成本未知先待测，不猜低效；后台候选逐项有受阻依据后才进入已获授权前台层，无须重复索取同范围许可；满足目标后不为遍历四层重放副作用 |
| 后台调用前保护 | 包括只读provider在内，先核实实际已实现且本目标有效的防抢焦能力，覆盖定位/worker/调用/验证/异步与撤销；记录进程/renderer/必要session/desktop归属、可检查生效约束、失效停止和安全退出依据。配置成功、LSFW调用、禁用顶层、隐藏、WS_EX_NOACTIVATE、权限位、无事件或固定sleep均不独立证明有效；无可靠保护时不从后台重试已知抢焦SetValue/未知副作用，记工具缺口并继续独立只读/身份调查 |
| 随包私有desktop入口 | references/scripts随skill分发；真实spawn worker的dispatch线程逐调用前后核验session/window station/desktop/input身份，目标根/renderer窗口另核验；既有QQ拒绝启动；登录显式调用LegacyIAccessiblePattern.DoDefaultAction并核对completed/call_completed，禁止通用click回退；完整树唯一selector、独立读回、并发原值保护；写结果unknown后停止新增setter，保留原失败和单列清理错误；正常/超时路径实查Job ActiveProcesses=0才结束保护。普通同desktop激活范围、Job外broker/显式切桌面局限与无GUI超时夹具的证明范围分别记录 |
| 前台证据与记忆分类 | before==after和foreground_changed=false只支持端点，期间未知；连续事件/鼠标证据仍是观测不是阻止机制。先抢焦再恢复仍按uses_foreground=true记，恢复成本不删；allow_foreground=true不是后台保护，也不将既有前台实验授权改写为可抢焦后台任务；保护新变体单独验证不继承旧结论；异步动作完成/可靠取消/相关处理终止前不按sleep撤保护 |
| 可观察性与接管 | JSON阶段/效果/归属/Job清理与图像预览区分；本轮无实时面板或接管入口，私有PrintWindow画面可用性未独立验收；SwitchDesktop改变输入desktop，当前helper不调用，未来接管须先停止新增自动化并明确前台阶段；不从QQ语义路径推广SendInput/真实键鼠/安全desktop支持 |
| see MCP文本形状 | 无图、有图、worker错误、非法worker载荷四支首块均为显式JSON对象文本，一次解码形状相同；有图追加image，无图保留metadata诊断及真实前台样本；真实MCP协议测试替换桌面执行，不启动或停止用户桌面worker |
| 本轮 skill 路线库 | 每条路线有触发→实际操作→验证/完整性→权限或工具缺口；至少包含原生child托管文本/状态、确属根内容时target空直读、Value/Text/Legacy交叉、Selection/Grid计数边界、组合定位、列表搜索/分页/分段导出、官方API/CLI/本地输出、UWP内容宿主、Electron单变量对照与wrapper/Control输入适配方向；不把提议当内置能力或把计数当已取全数据 |
| 性能 | 同一窗口/任务核验常用七项探测未被改成全量探测；记录读树样本及环境，不能用历史 QQ 时延作硬阈值 |

本轮临时真实HTTP服务先验证16项工具清单与`see(hwnd=0)`经真实worker在provider之前的not_started错误返回；后续另在私有desktop临时HTTP服务中，以其真实受保护worker和QQ唯一ComboBox selector，完成ValuePattern.Value的定位→pattern→调用→字符串投影成功链，且核对HTTP服务后代worker归属和专属进程清理。QQ搜索写入/恢复仍走进程内FastMCP→worker，不能扩大为HTTP setter已验证。改名前这轮GUI实测时已安装8765端口未监听，没有当时的部署或重启后服务验收；后续DeskWeft改名服务验收另见§0.1，不能反向补成旧GUI路线的HTTP setter复验。具体版本、成本和范围见[QQ/微信报告](../reports/2026-11-08-qq-wechat-live.md)，不把临时服务成功写成已安装服务已部署。

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
