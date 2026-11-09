# 前台保护：调查、隔离候选与验收

本参考用于后台路线缺少防抢焦能力、准备隔离实验或审核已有保护证据时。
路线仍按 [SKILL.md](../SKILL.md) 的后台高效→后台低效→前台高效→前台低效推进。
下文给出调查与实现条件，不能代替现场能力，也不增加重启、关闭或发送消息的授权。
已有同范围授权继续使用；缺少某个动作授权只阻塞该动作，继续其他可行调查。

**历史状态：2026-11-08，当时随包入口已在本机 QQ 9.9.22 完成显式语义登录、直接搜索读写、
恢复与清理的完整复验，可作探索起点；不表示 2026-11-09 当前构建或已安装服务已复验。**
下文“本轮/当前样本/复验”均指所述历史轮次，除非另列日期、源码版本与新证据。
该历史轮次核对真实 worker 的逐调用
session/window station/desktop、31 个 QQ root/renderer HWND 和 Job 清理归零；
登录仅用显式 LegacyIAccessiblePattern.DoDefaultAction；搜索没有 Legacy 预聚焦，
直接 ValuePattern.SetValue 后独立读回并精确恢复原值。
输入 desktop 的 576 个样本均为 Default，未观察到切桌面；前台端点相同，但收到
33 条前台/焦点事件，其中 19 条为 Explorer、9 条为 DeepSeek Harness、5 条为 Terminal，
没有归属到已知 QQ PID 的事件。这些证据不等于“用户前台全程不变”，鼠标未观测。
较早两轮登录使用通用 click，日志未保留实际分支，不能据此证明登录绝无真实键鼠兜底。
当前 runner 拒绝 fallback，日志保留显式语义请求/响应路径与脱敏参数，已另做本轮
整体验证，不沿用旧登录成功作证明。
较早 v2 的 Legacy 预聚焦变体和失败历史分别保留，不与直接 setter 合并。
新应用、版本或动作仍按下文验收；生产 MCP 本身没有自动隔离能力。

## 先决定本次能够做什么

| 条件 | 继续方式 |
|---|---|
| 已有实现、作用范围覆盖本次调用，且可检查的保护约束已经生效 | 保持保护，执行已授权的最小闭环，再核对效果、异步完成与清理 |
| 只有开关设置成功、窗口隐藏/禁用或没有前台事件 | 保护仍待核验；先做身份、归属、接口与实现调查，不发潜在抢焦 provider 调用 |
| 某个保护方案在此环境已失败 | 保留失败机制和范围，调查其他候选；不能将它重新标成有效保护后重放已知抢焦动作 |
| 保护能力尚未封装或无法检查失效/安全退出 | 记录具体工具缺口；继续有依据的其他后台通道，不用 allow_foreground=true 代替保护 |
| 合理后台候选逐条受阻，已有前台实验授权 | 明确降级到前台层；实验结果如实记录前台副作用及完整成本 |

观测与保护分别验收。前台事件 hook、前后台端点、鼠标位置和输入桌面采样用于发现
副作用及描述证据覆盖范围；这些观测不会阻止激活。检测到变化后停止或抢回属于
事后处理，不能弥补调用前没有保护。不能拿真实用户输入前台反复验证已知抢焦 setter。

## 本轮已经证明和没有证明的事实

以下样本只适用于当时目标和调用条件，不外推为所有 Windows 应用的结论。

| 方案/观察 | 实际证据 | 当前结论 |
|---|---|---|
| 从后台调用 LockSetForegroundWindow | 返回 false、error=5 | 没有取得锁；不能写成“已锁住但被应用绕过” |
| 禁用当时已知的 QQ 可见顶层窗口 | enabled child renderer 先成为前台，随后父窗口成为前台；setter 报 UIA_E_ELEMENTNOTENABLED，值未改变；原 enabled 状态已恢复 | 该覆盖范围既未阻止抢焦，也未完成写入；仅禁用已知顶层不能充作有效保护 |
| WS_EX_NOACTIVATE | 本轮没有足够的完整保护验收证据 | 不承诺它阻止任意 provider/子窗口激活；不将它写成已经实测失败或成功 |
| 抢焦后切回原窗口 | 即使末尾 HWND 相同，中途仍可能发生接管 | 是恢复成本，归入发生前台副作用的路线 |
| 非输入桌面的首次 runner 与 QQ | runner、QQ 主界面和部分窗口归属已观察到；真实 worker 归属断言失败，闭环未完成 | 首次试验失败保留；不能用启动成功代替 worker 验收 |
| 修正后的非输入桌面 v2 | 真实 worker、29 个窗口归属通过；Legacy 预聚焦后写入、独立读回、恢复和实验 QQ 关闭通过；输入 desktop 采样不变，用户前台端点不同 | 该历史效果样本通过；不是无预聚焦的直接 setter，也没有随包完整生命周期成本 |
| 历史随包直接 setter 两次样本 | 各轮真实 worker、31 个 QQ HWND、独立读回、精确恢复、QQ/worker 关闭和 Job 归零通过；历史复验发现用户 desktop 的 23 条事件，无已知 QQ PID 归属 | 搜索与清理样本保留；登录通用 click 的实际分支未留存，不能证明该段没有真实输入兜底，当前显式语义登录另验 |
| 当前显式语义登录＋直接 setter 完整样本 | 登录请求/响应均为 LegacyIAccessiblePattern.DoDefaultAction、args=[]、completed/call_completed；后续完整主树与搜索/恢复通过，未调用 click；逐调用真实 worker、31 个 HWND、QQ/worker 关闭和 Job 归零均通过 | 本轮完整入口验收通过；事件归属与鼠标未观测的边界仍保留，不扩展到真实键鼠路线 |
| 随包 2 秒超时清理 | 无 GUI runner 创建后代后挂起，父级预期超时并确认两者退出；Job ActiveProcesses=0，清理无错误 | 已验收该 helper 的后代超时清理；不证明任意 provider 异步动作可以取消 |

可在开发仓库的本轮记录中按 `qq-guarded-background.json`、`desktop-identity.json`、
`qq-isolated-desktop.json`、`qq-isolated-desktop-child.json` 及其 `-v2` 变体查原始证据；
`desktop_launcher.py` / `desktop_qq.py` 是当时的实验实现名称。随包样本另见
`package-identity-parent.json`、`package-qq-direct-parent.json`、
`package-qq-final-parent.json`、`package-qq-semantic-login-parent.json` 和
`package-timeout-parent.json`，各子结果从本轮父报告的
`child_out` 获取。这些原始记录在开发仓库 `.superpowers/sdd/2026-11-08-chatapps-live/`，
不随 skill 安装；随包可执行入口见后文，不能照抄历史 HWND、PID 或 desktop 名。
记录后续成功变体时另记机制与条件，保留上述失败历史，不覆盖成统一“成功”。

| 随包样本 | 本轮结果与内部时间 | 调用与观测范围 |
|---|---|---|
| identity | 父/子完成、Job 清理通过；lifecycle 3566.870 ms，preparation 14.586 ms，cleanup 1.253 ms，runner 3120.6 ms | 不启动 QQ；1 次真实 worker 无效 HWND 预检 1641.4 ms，无全树；59 个输入样本，实际间隔中位 62.395 ms、最大 79.445 ms |
| 首次直接 QQ | 效果/恢复/QQ 与 worker 关闭通过，Job 归零；lifecycle 32957.268 ms，preparation 14.009 ms，cleanup 1.399 ms，runner 32468.1 ms | 11 次调用 27749.0 ms，其中搜索闭环 6 次 17086.5 ms，2 次显式全树；532 个输入样本，实际间隔中位 62.273 ms、最大 72.463 ms；前台端点相同、事件为空 |
| 历史直接 QQ 复验 | 效果/恢复/QQ 与 worker 关闭通过，Job 归零；lifecycle 34009.727 ms，preparation 13.509 ms，cleanup 1.262 ms，runner 33524.2 ms | 11 次调用 28731.2 ms，其中搜索闭环 6 次 17894.4 ms，2 次显式全树；549 个输入样本，实际间隔中位 62.239 ms、最大 68.405 ms；前台端点相同但有 23 条事件：13 Edge、9 Terminal、1 PID 0 未知 |
| 当前显式语义登录完整 QQ 复验 | 效果/恢复/QQ 与 worker 关闭通过，Job 归零；lifecycle 35660.522 ms，preparation 13.050 ms，cleanup 1.970 ms，runner 35152.4 ms | 11 次调用 30370.0 ms，其中搜索闭环 6 次 19402.8 ms，2 次显式全树；576 个输入样本，实际间隔中位 62.177 ms、最大 73.683 ms，最小 0.080 ms 含收尾采样；前台端点相同但有上述 33 条事件 |
| 预期超时清理 | 父级 ok=false、TimeoutError；清理通过、Job 归零；lifecycle 2059.687 ms，preparation 13.483 ms，cleanup 3.450 ms | 2 秒超时；35 个输入样本，实际间隔中位 62.320 ms、最大 67.259 ms；输入 desktop 不变，未观察到切换 |

这些时间来自各轮自身测量，内部项互相包含，不能相加。lifecycle 包含 launcher
计时开始后的准备、运行和清理，但不含此前的解释器/依赖启动和外层工具往返；完整
用户路线比较还需外部计时。50 ms 是采样循环配置的等待值，实际时间戳间隔如表所示，
不能写成连续监测或固定 50 ms。各次直接 QQ 样本的 exe 为
`C:\Program Files\Tencent\QQ.exe`，应用版本 9.9.22 来自 child_cmdline；FileVersion
另为 9.9.19.35469。当前显式语义登录复验的真实 worker 为 PID 27112/TID 2560，
这些仅为样本归属证据。该轮事件 PID 11604=explorer.exe、22828=DeepSeek Harness.exe、
8720=WindowsTerminal.exe，均由当场进程查询核名；用户活动造成的事件不自动归因给 QQ。
搜索闭环的六次调用是原 Value、SetValue、Value 读回、恢复前 Value、恢复 SetValue、
恢复后 Value；没有插入 focus 调用。早期 v2 的搜索/导航 8 次为 22165.8 ms、全部
12 请求为 32673.6 ms，均不含完整保护/清理，不能当作完整总成本或与直接变体合并。

## 调查步骤：先建立范围，再查保护约束

1. **核对现场工具。** 查看实际注册的工具、可用命令及代码中的真实实现。
   区分工具权限门、激活调用、worker/IPC、保护实现与观测器；不要从参数名推测能力。
   只存在工具提案、文档或脚本文件时，仍须检查它能否在当前环境运行并按失败关闭。
   没有对应能力就记“工具未实现”，不编造接口调用。
2. **保存目标身份。** 用不触发目标 provider 的窗口/进程查询核对 HWND→线程→PID、
   exe、进程创建时间、版本来源、session、window station、desktop；列出实际内容窗、
   renderer、同应用其他顶层及已知 broker。标题相同或同一进程名不足以证明同一目标。
   HWND/PID 可能复用，调用前及清理前都要重新核验归属。
3. **保存用户输入环境。** 在用户所在 session/window station 核对输入 desktop、
   前台 HWND 与鼠标状态。OpenInputDesktop 返回接收用户输入的桌面句柄；比较时保留
   session、window station 和 desktop 的组合身份，不能只比较一个桌面名称。
   锁屏、UAC、安全桌面、RDP 断开/重连或用户主动切桌面都可能改变适用条件；
   观察无法覆盖时暂停发动作，不能自动切回替用户决定。
4. **把抢焦来源拆开。** 调查定位/读树、实际 getter/setter、专用工具、provider 内部
   实现、异步任务和清理各自可能的激活路径。一次 setter 抢焦不能证明所有 getter
   抢焦；同样，Get 名称、只读白名单、API 返回成功都不证明没有激活副作用。
   保护未生效时用实现/接口资料与独立安全通道调查，不重跑潜在抢焦调用来补证。
5. **给保护写出可检查的契约。** 说明它实际阻止什么、约束如何生效、哪些相关窗口/
   线程/进程受约束、可能怎样失效、如何在失效前拦住下一次调用、怎样让已发动作
   完成/取消/终止。只会记录 before/after 或超时后恢复前台的实现不满足此契约。
6. **核对异步与退出。** 把 provider 返回后的事件处理、子进程、worker 重建、重试、
   broker 转发也放入范围。queued/unknown 尚未查清时停止发替代动作，保留隔离并
   用不重复副作用的状态通道调查。未能判断何时可安全撤保护时，先补此工具缺口。

保护记录至少包含以下字段；它们可以并入 memory 的实测记录，无需新增交接文件。

| 字段 | 可验收证据 |
|---|---|
| 实现与版本 | 当前可用入口、实现位置/版本、依赖、能力已实现或尚缺失 |
| 调用前约束 | 能被核对的系统/机制状态，覆盖目标与此次动作的适用依据；不是单独一个“enabled=true” |
| 作用范围 | session/window station/desktop，窗口与创建它的线程，renderer/broker，真实执行 worker |
| 失效检测与阻止 | 检查时机、失败后拒绝继续发动作的路径；观测到抢焦才停止的局限另记 |
| 异步结束依据 | 业务完成且相关处理已终止、可靠取消，或本次相关执行环境全部结束；说明依据来源 |
| 退出与恢复 | 什么状态下撤销、失败时怎样保持约束、原值/窗口状态/句柄/进程怎样核验 |
| 成本与观测 | 从安装保护到清理的全链路时间、调用/全树次数；事件/采样范围、间隔与未知部分 |

## 路线一：复用现场已有且验收的保护

本路线没有预设工具名。只有当前环境确实提供相应能力时才使用。

1. 核对实现契约、适用版本与实际作用范围；确认没有把授权开关或日志字段误认成保护。
2. 取得本次保护实例并检查返回值/错误和可检验约束。取得失败、目标身份变化、
   新 renderer/worker 未纳入或约束不可读时，拒绝进入调用阶段，记录未发动作。
3. 在约束持续有效的条件下定位、读取原状态、执行最小授权动作并验证业务效果。
   作用范围发生变化或执行状态未知时停止新增动作，继续受保护的状态调查。
4. 按机制契约证明相关异步处理已结束，再恢复状态并撤销保护。恢复本身也受保护，
   不能为“清理”无保护重跑已知抢焦动作。
5. 核验保护确实撤销、状态确实恢复，保留全部证据与完整成本。仅某次无前台事件
   不能把同工具的其他控件、版本或未知调用自动纳入已验收范围。

LockSetForegroundWindow 有具体调用者与失效条件：微软文档将其描述为前台进程禁用
SetForegroundWindow 调用，且 ALT 或某些用户操作会重新允许调用。因此后台调用失败
不能靠忽略返回值补救；即使某次取得成功，也须单独证明适用范围和保护持续条件。
不要为了取得锁而先激活自动化程序、改变用户前台，再把整段称为后台完成。

## 路线二：非输入 desktop（本环境已有复用起点）

Windows desktop 承载窗口等 UI 对象，交互 window station 同时只有一个 desktop
接收用户输入。可以据此研究“目标和执行线程都留在非输入 desktop”的候选，
但创建 desktop 不等于已证明应用完整受约束。拥有相应权限的进程可以请求切换
输入 desktop；跨桌面单实例、broker 或另开的窗口也必须调查。此候选不能直接
承诺隔离任意应用的所有行为，更不能替代真实用户前台上的调用前验收。

### 准备与启动

1. 确认本次允许的启动/关闭范围，记录实验目标、可逆动作及停止条件。已有授权
   继续有效；普通读任务不自动允许关闭用户应用或重启登录会话。
2. 调查目标是否单实例、会复用哪些已有进程/服务以及新启动参数能否生效。
   当前用户 desktop 上的旧实例可能接管请求时，不启动试错；先解决实例归属。
   缺少关闭/隔离实例的权限或工具，就记该候选受阻，继续其他后台方向。
3. 由持有清理责任的控制器创建本次唯一命名 desktop，记录创建结果和句柄归属。
   CreateDesktop 同名时也可能返回已有对象，不能把返回非空当作新隔离对象已确认。
   控制器保留用户输入环境观测，不调用 SwitchDesktop，不模拟用户键鼠去寻找实验窗。
4. 用明确的 window-station\desktop 启动专用 runner；实现时核对 CreateProcess 的
   STARTUPINFO.lpDesktop、句柄继承和所需权限。多个继承 desktop 句柄会使线程连接
   结果不确定；启动设置不能代替运行时检查。
5. 在初始化 UIA/COM、创建窗口或 hook 前安排执行线程。SetThreadDesktop 对已有窗口
   或 hook 的线程可能失败；不要在现有生产 worker 上忽略失败后继续发 provider 调用。
   可选择新建已指定 desktop 的执行环境，再逐项核验实际归属。
6. 若以 Job Object 管理本次进程树，先配置 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE，
   挂起创建 runner，核验 AssignProcessToJobObject 成功后才 ResumeThread。这样
   runner 开始创建后代前即受本次 Job 管理；配置或归属失败时不运行任务。
   不开启 breakaway，不继承 Job 句柄给子进程，并调查已有 broker/单实例等 Job 外
   路径。Job 负责本次执行环境的生命周期，不负责阻止 foreground/desktop 切换。

### 调用前必须通过的检查

1. runner 报告自己的 PID/TID、session/window station/desktop，并与控制器预期一致；
   该 desktop 必须与当时输入 desktop 不同。controller 仍能核验用户输入环境。
2. **真实 UIA dispatch 线程**在处理请求前报告自己的 PID/TID 与桌面归属，核对它
   就是本次实际 worker。主线程、任选的进程线程或 runner 自己的归属不能代替它；
   multiprocessing spawn、线程池、COM/provider host 与 worker 重建都须重新核验。
   已在 Default desktop 运行的 HTTP MCP/worker 不能直接当作私有桌面执行端；
   本轮做法是在私有 runner 内新建 Client(server.mcp)，由它再 spawn 新 worker，
   并在 spawn 重导入入口安装逐调用的 dispatch 核验。不能只把私有窗口 HWND
   传给旧连接，或只把现有 HTTP 客户端搬进 runner 后就认为服务端随之搬迁。
3. 在受控启动范围内启动目标，核对新进程创建时间和实际窗口。对主内容窗口、
   顶层窗口及 renderer 子窗口，用创建窗口的线程核对 desktop；列清已知 broker
   与其他激活路径的覆盖依据。不能只看一个最大窗口、一个标题或启动命令返回的 PID。
4. 明确本次普通窗口激活路径的约束：没有旧实例接管，目标 root/renderer/真实
   dispatch 同在非输入 desktop，任务链不调用 SwitchDesktop/SendInput，也没有
   已知的输入 desktop broker 转发。核对这些条件后，可依照 OS desktop 的作用范围
   研究本次普通激活动作；仅启动成功、未核对 worker/renderer/实例/调用路径时仍
   不足。新窗口和执行环境变化须重新核验；观测到变化才停止也不等同于预先约束。
   不要求证明任意同权限程序永远无法显式创建输入桌面窗口或切桌面，这属于该方案
   的适用边界；需要防御此类行为的目标另选隔离机制。
5. 核验整个调用链和恢复链均不会使用输入 desktop 的键鼠/前台兜底；前台权限门
   即使在隔离环境中仍按工具契约处理，allow_foreground=true 也不负责隔离。
6. 调用前启动用户输入 desktop 的事件/时序观测，并记录实际覆盖范围、采样间隔、
   hook 注册状态及可能丢失。非输入 desktop 的局部激活与用户 desktop 的接管分开
   记录；缺少鼠标观测就写未观测。观测用于核查，不替代前四项约束证据。

任一项失败都先阻止后续 provider 调用。工作仍可继续在身份、启动参数、线程归属、
实现与清理等不依赖该危险调用的调查上；不能把“worker 断言报错”写成动作已试失败。

### 最小效果与恢复闭环

仅在上述调用前条件满足后执行，保持保护直到相关异步处理结束。

1. 以当前完整树的唯一 selector 或已核验 child HWND 定位目标；先读并保存原值。
   应用或树尚未稳定、selector 无匹配/歧义时停止动作，重新查明定位条件。
2. 使用任务授权范围内的可逆动作验证一件事，例如独立的搜索字段读写。
   不扩展为发消息、联系人操作或提交业务；不把设置返回 ok 当作效果成立。
3. 在真实 dispatch 线程调用前后都保存归属证据；再读回值或核对明确业务标志。
   setter 报错、effect 未验证、队列未知或动作被保护阻断时，按实际状态记录。
4. 仅在写入已明确完成、逐调用保护证据有效且后续没有阻塞状态时，保持隔离，
   读取当下状态后恢复原值；若发现非本次预期的并发变化，不覆盖它。
   selector 变化时重新观察和核验身份，不能删除条件后取第一个同类控件来恢复。
5. 核验原值/状态精确恢复，并取得相关处理结束的证据。固定等待、队列已接收、
   一次计数不变、worker 超时都不足以证明可撤隔离。
6. 连同清理结果核对用户输入 desktop、前台事件与鼠标观测。仅 before==after 时
   写“前后采样相同，期间未知”；事件无记录时说明 hook 覆盖与遗漏可能，不写绝无抢焦。

### 清理与异常路径

清理仍属于被保护的闭环；控制器与 runner 都要有责任边界，不能仅依赖 runner 的 finally。

1. 停止接受新动作，查明已发请求是否完成、可靠取消或仍为 unknown。查不清时保持
   隔离，不在输入 desktop 上重放动作、不撤保护后继续等待它自己结束。
   随包 runner 对 `delivery=queued`、unknown、缺少 `call_completed:true` 或真实
   worker 保护证据的写入立即停止后续 provider 调用，也不再发恢复 getter/setter；
   记录恢复跳过/未确认，由父级 Job 结束本次独占临时 QQ，报告该轮未完成。
   仅原值或 token 读回相符，不能证明更早的异步动作已结束。
2. 按本次授权恢复原值和原窗口状态。恢复失败时保留错误与现状，不能将整条路线
   记为成功；若必须终止实验应用，只作用于本次已核验归属的执行环境。
3. 结束本次拥有的目标/renderer/worker/runner，并验证相应进程确已退出；或用机制
   自身可检验的契约证明全部相关处理已终止。外部 broker 未排除时不能用“父进程退出”
   证明异步已清空。PID、exe、创建时间与所属 desktop 都用于避免关闭无关进程。
4. 超时或归属断言失败时，控制器也必须能执行上述检查。强停 runner 不保证它的
   finally 执行，也不保证子进程一并结束；控制器须保有可核验的归属/清理信息。
   尚未实现这条异常路径时，不将正常路径偶然退出当作可复用清理能力。
5. 使用 Job 时先结束相关处理、等待退出并释放本方进程/线程引用，再保持 Job
   句柄查询 ActiveProcesses，直到实测为 0；记录终止、查询和归零结果。
   TerminateJobObject/CloseHandle 返回成功不单独证明已经归零；查询失败、仍非零
   或超时都记清理未完成。还要另行处置已发现的 Job 外本次执行路径。
6. 按句柄来源释放资源。CloseDesktop 关闭的是句柄，不是“杀掉其上全部进程”；
   它返回成功不能单独证明没有遗留应用或异步动作。不要 CloseDesktop 关闭
   GetThreadDesktop 返回的句柄；自行 Create/Open 得到的句柄分别记录释放结果。
   相关执行环境未安全结束时，不把句柄释放当作撤保护的充分依据。
7. 确认事件 hook/监测线程已撤除、worker 已关闭、无本次遗留进程，核对用户 desktop
   与原应用应有状态。用户原实例的重新打开只沿用已有授权和已记录参数，不猜测
   登录状态或默认参数。清理受阻则如实报告剩余状态与下一步，不宣告保护已安全撤销。
   随包 runner 保留主要 stage/error；worker 关闭、恢复等后续失败另记 secondary_errors，
   不覆盖首次失败，并尽力写出脱敏最终 JSON。

## 随 skill 交付的执行入口

当前产品名为DeskWeft（Python包/CLI为`deskweft`）。本文已取得的实测仍属于改名前源码；以下当前命令用于新版本复验，不能把旧轮次的效果或哈希倒填为改名后已复验。

- [private_desktop.py](../scripts/private_desktop.py)：标准库 launcher，创建非输入 desktop，
  挂起创建 runner 并纳入本次 Job 后再运行，监测输入环境，核验 Job 清理并释放句柄。
- [qq_private_probe.py](../scripts/qq_private_probe.py)：使用当前生产 DeskWeft 的最小 runner，
  提供 identity 预检和 QQ 的直接 ValuePattern.SetValue 搜索闭环。只在没有现存 QQ
  时启动新实例；不会关闭旧 QQ、选择其他账号、填写聊天输入或发送消息。原搜索值
  只留内存用于恢复，日志保留结构、计数、公开标志和非公开文本摘要，不保存会话正文。

使用含 deskweft/FastMCP/psutil 依赖的 Python 环境，并指明要验证的生产 deskweft 源码目录。
`--repo` 使 runner 和 spawn worker 使用这份实现；不会连接用户桌面上已经运行的旧 MCP。
先将以下路径替换为现场实际值。安装在个人 skills 目录时，`$skillDir` 指向安装后的目录，
不能假设 skill 一定位于 deskweft 仓库中；`$pythonExe` 指向具备相同依赖的解释器。

```powershell
$repoDir = 'C:\Users\32677\source\deskweft'
$skillDir = Join-Path $repoDir 'skills\windows-app-automation'
$pythonExe = Join-Path $env:LOCALAPPDATA 'deskweft\.venv\Scripts\python.exe'
$probeOutDir = Join-Path $repoDir 'tmp\private-desktop'
New-Item -ItemType Directory -Path $probeOutDir -Force | Out-Null
& $pythonExe -X utf8 -B "$skillDir\scripts\private_desktop.py" --out "$probeOutDir\identity.json" -- "$skillDir\scripts\qq_private_probe.py" identity --repo $repoDir
```

identity 预检不启动 QQ，通过真实 worker 对无效 HWND 的拒绝路径取得 dispatch 线程证据。
父报告的 `child_out` 给出带本次唯一 desktop 名的子 JSON 路径；读取它，不能沿用上轮
同名子文件。核对父进程退出结果、子 JSON 的 `completed:true`、真实 worker 的前后
归属、用户输入 desktop 观测、Job 清理归零及句柄释放；父级返回成功而子结果缺失/
未完成仍不算通过。
脚本缺失、依赖未安装或身份检查失败时记具体工具缺口，不跳过预检直接做动作。

QQ 步骤须先具备本次启动、关闭和可逆搜索实验的授权；已获授权无需重复询问。
只有此前没有 QQ 实例、目标 exe 和本版本适用前提都核对后再运行。下面的登录 flag
表示调用者已经取得“登录当前已保留账户”的范围授权，不会自动选择账号；没有该授权
时省略它，遇到登录页会停止。不要为让脚本运行而静默关闭用户正在使用的 QQ。

```powershell
& $pythonExe -X utf8 -B "$skillDir\scripts\private_desktop.py" --out "$probeOutDir\qq.json" -- "$skillDir\scripts\qq_private_probe.py" qq --repo $repoDir --exe 'C:\Program Files\Tencent\QQ.exe' --allow-existing-account-login
```

launcher 自动给 runner 追加本次唯一 `--expected-desktop` 和子结果 `--out`。
QQ runner 按当前完整树确认唯一登录按钮和唯一 ComboBoxControl；空树、截断、歧义、
已有实例或未知并发文本都拒绝继续。它先读取原值，再直接调用 SetValue、独立 Value
读回，仍在隔离内恢复原值并核验，最后关闭本次 QQ/worker；父层完成 Job 清理。
登录只用显式 `LegacyIAccessiblePattern.DoDefaultAction`，不调用通用 click；pattern
缺失、失败、queued/unknown 或缺少 `ok + completed + call_completed:true` 时停止，
不尝试其他登录动作，也不继续搜索。每次 invoke_pattern 的请求保留 pattern/method、
selector 与参数结构；非公开 name/文本参数仅留摘要，响应语义路由和保护证据一同保存。
不会退回 Legacy 预聚焦、坐标、SendInput 或 Default desktop 的旧 MCP 来强行完成。
直接 setter 变体与 v2 预聚焦变体分别记录；失败/unknown 不自动改用另一条路线重放。

读取本次两个 JSON，逐项核对：

1. 父级 `ok:true`、`runner_exit_code:0`、`runner_completed:true`；子级 `completed:true`。
   QQ 模式还需 `effect_verified:true`、`search_restored_exactly:true`、
   `isolated_qq_closed:true` 和 `worker_closed:true`。`isolated_qq_closed` 仅覆盖 runner
   核验到的同 exe QQ 集合，不能独立证明所有 renderer/其他后代都结束。
2. 父级 `cleanup.complete:true`、`cleanup.active_processes:0` 且 `cleanup.errors` 为空；
   子结果中每次真实 `_probe_worker` 的 PID/TID、session/window station、前后
   `current_desktop` 都与本次私有环境一致。不能只抽查主树那一次 worker 记录。
3. `input_desktop_changes` 为空、`desktop_switch_observed:false`，前后 `input_full`
   一致；`observation.installed/removed` 为 true、errors 为空。采样循环默认等待
   50 ms，实际间隔以 `input_samples` 时间戳计算；事件 hook 也有覆盖边界，
   不把采样当作连续硬阻止。
4. 检查 `observation.events` 的真实前台/焦点事件及目标进程归属，保存未知归属。
   `foreground_or_focus_changed:true` 可以来自用户活动，不自行归因；即使 `ok:true`
   也不表示用户始终停留在同一前台窗口。现有 helper 不采集鼠标位置，鼠标观测写
   “未观测”，不要由没有 SendInput 推导成已经测得鼠标全程未动。
5. 分别保存父级 `preparation_ms`、`cleanup_ms`、`lifecycle_ms`，子级
   `runner_wall_ms` 与各 call 的 `wall_ms`；这些内部时间不覆盖命令启动前的解释器/
   依赖加载和外层工具往返。需要完整路线比较时加上外部计时，说明测量边界和摊销，
   不把各 call 之和当成含保护与清理的总耗时。

上述 identity、历史直接 QQ 与预期超时清理分别保留原轮证据；当时的显式语义登录入口
曾另行完成上述完整复验，本次代码修复未重跑该真实应用闭环。脚本正常退出仍须核对完整验收表，有限样本
不自动升级可信等级或覆盖其他任务。固定启动/登录等待不是
异步排空证明；业务状态
另行核验，结束前本次相关执行环境与 Job 都必须确认清理。两条命令分开串行运行，
不要与同账号/同应用其他实验并发。

## 查看私有桌面与操作边界

当前没有私有桌面只读预览面板。MCP 的 private_desktop 已可 create/status/show/hide/close，
其中 show/hide/close 会涉及输入桌面变化并要求前台授权；它管理自己创建的桌面，
不会接管下面 helper 的 Job，也不会把现有目标或服务 worker 迁入隔离环境。
两个随包脚本保存身份、调用、观测与清理证据，QQ runner 不保存窗口截图或会话画面。

| 需求 | 当前能力与处理方式 |
|---|---|
| 在用户当前桌面只读查看私有桌面的画面 | 尚未实现的候选：在私有 runner 内采集，再通过 IPC 回传到用户当前桌面的查看界面，全程不切输入 desktop。PrintWindow/现有截图通道可能因应用、GPU 或渲染条件返回空白，先按实际应用验证；不能声称已有预览面板可调用 |
| 直接查看或接管私有 desktop | 显式 SwitchDesktop 会改变输入 desktop，占用用户输入环境，属于前台/接管操作。先停止发动作，查清已发动作，暂停或安全结束自动化并核验现场，再在已有授权范围内安排独立接管流程；当前 helper 不调用 SwitchDesktop，检测到输入 desktop 变化会终止本次试验并清理 |
| 任务结束后再次打开私有 desktop 看现场 | 本流程会结束本次相关进程、释放资源，不能假设那个 desktop 仍可接管或有画面回放。查看留存的结构与日志证据；截图/录像留存属于另行实现并授权的能力 |
| 把需要目标局部激活/焦点的语义动作放入私有 desktop | 可研究对应普通窗口路径。本机已验证 QQ 登录语义动作、直接 ValuePattern.SetValue 搜索及读回/恢复；v2 另验证过 Legacy 预聚焦变体。每种新动作仍核对作用范围和效果，不推广为任意前台操作均可后台完成 |
| 在私有 desktop 使用 SendInput、全局键鼠、剪贴板或安全 desktop | 没有通用隔离保证。SendInput/全局输入不能只凭目标 HWND 位于私有 desktop 就当作后台可用；安全 desktop、UAC 和真实键鼠输入另有约束。当前 QQ runner 不采用这些兜底，也不据语义动作成功承诺它们可用 |
| 操作确实依赖系统输入 desktop 的真实键鼠 | 尚未实现的更重候选：使用单独 Windows 交互会话或虚拟机，在其内部前台执行并回传画面。它需要新环境、登录与独立实测，不是当前 private desktop 或现有 MCP 已具备的能力；只在覆盖相同任务的候选中比较包含环境准备、执行和清理的完整成本 |

只读预览与接管是不同能力。新增前者须保留后台约束与隐私范围；新增后者须有明确
暂停/接管/恢复契约，重新核验窗口、worker、selector、输入环境和未完成动作。当前
实现没有暂停后接管再恢复同一任务的协议，不能在脚本运行中通过切桌面临时补上它。

## 何时能把实验提升为本环境可复用路线

必须保存一次贯穿准备、调用、验证、恢复与清理的完整证据，再根据重复样本说明稳定性。
不能拼接不同轮次中互不覆盖的“各项成功”，或用旧版路线的 rank 代替本条件验收。

| 验收项 | 达到的结果 |
|---|---|
| 调用前保护 | 实现存在，约束有效且范围覆盖目标、真实执行线程和本次激活路径；失败时拒绝继续调用 |
| 真实任务效果 | 精确定位；实际动作与独立读回/业务标志一致；覆盖用户要求的字段与范围 |
| 恢复 | 本次改变的状态按约定恢复；并发变化得到处理；没有无保护的恢复动作 |
| 输入环境 | 保护机制适用依据和覆盖时段观测齐全；端点、事件、鼠标及缺失范围分开报告 |
| 异步与退出 | 实际完成/可靠取消/相关处理终止有依据；unknown 不被当作未执行或安全撤保护 |
| 异常清理 | runner 失联、worker 超时、归属失败也有清理证据；无孤儿相关进程或未释放的自有资源 |
| 完整成本 | 保护安装/核验→启动/定位→worker/IPC→动作→等待/验证→恢复/清理，全阶段耗时及调用/全树次数可核对 |
| 复用边界 | 版本、exe、flags、session/desktop 条件、selector、单实例/broker 前提和失效条件清楚 |

首次完整成功也只证明本版本、本条件、本动作的样本，不自动证明其他应用或全部 UIA
方法都可后台运行。新 renderer、worker 重建、进程重启、权限/session 变化、目标更新、
单实例接管、锁屏或 RDP 状态变化时重新核验相应前提。隔离后树/截图/渲染不可用只
证明该条件下相关通道受限；不能通过切到实验 desktop 补图后继续把闭环称为后台。

独立 desktop 内部可能出现局部激活。记录它与用户输入环境的区别，并说明该新变体
满足的是哪项后台约束；不修改旧未保护路线的 uses_foreground=true。新变体未完成
验收、缺少副作用范围或当前仍是实验状态时，仍按未知副作用保守记 uses_foreground=true、
rank=0。只有取得本条件的完整后台证据后才按证据记录；可信 rank 仍不代表效率。
隔离的启动/清理成本可能高于其他后台候选，仍只在同层、同任务覆盖下比较完整成本。
