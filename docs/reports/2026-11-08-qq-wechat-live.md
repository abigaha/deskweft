# QQ / 微信真实应用验证记录

改名说明（2026-11-08）：项目现名为DeskWeft（Python包/CLI：`deskweft`）。本报告原有的`winmcp`命令、路径、模块、desktop名称及源码哈希保留为改名前原始证据，不倒填为新名称；纯命名修改须另经新离线与部署验收，也不表示本报告GUI任务已重跑。当前入口和兼容存储规则见[实施交接](../specs/2026-11-08-implementation-handoff.md)。

日期：2026-11-08。下文记录已取得的真实应用、隔离desktop、临时HTTP和清理JSON及相应测试输出；未完成方向按具体范围保留。原始资料在本机 `.superpowers/sdd/2026-11-08-chatapps-live/`，本文不公开联系人、会话名称、消息正文、账号或应用截图。

QQ 在目标非前台时可读树、Legacy 页面导航有效的结果已记录，但这批端点观测没有证明有效调用前保护，不能据此归为满足当前门槛的后台方案。搜索 SetValue 则已实际夺取前台。微信的本次 UIA/MSAA 调查仍未取得会话内容；Ctrl+F 调用成功也没有足够焦点证据，因此没有继续输入聊天文字。两者均未验证完整联系人/聊天列表采集。

后续随skill交付的私有desktop变体在QQ9.9.22上完成显式语义登录、直接语义写入、独立读回、精确恢复及Job活动归零，最终完整helper生命周期约35.7秒；它与旧无保护路线分开记录。该机制覆盖已核验留在非输入desktop的普通窗口激活路径，不是通用安全沙箱、画面预览或键鼠后台模拟器，用户desktop上的事件与未知范围仍逐轮保留。

本报告与 [ItemContainer 合成夹具报告](2026-11-08-itemcontainer-live.md)、设计稿 §7 和 README 的历史数字分开计证。此处不是此前 128 项实测的重跑，节点数也不能与旧样本直接比较。

## 环境、权限与调用路径

| 项目 | 本轮记录 |
|---|---|
| Windows | Windows-11-10.0.26300-SP0 |
| Python | 3.14.7，MSC v.1944 64 bit (AMD64)；构建标签 `tags/v3.14.7:823f032, Aug 5 2026, 10:51:32` |
| 环境 | `%LOCALAPPDATA%\winmcp\.venv\Scripts\python.exe`，导入当前工作仓库 |
| windows-mcp / FastMCP | 0.8.8 / 4.1.6 |
| QQ | `C:\Program Files\Tencent\QQ.exe`；app_info 版本9.9.22，source=child_cmdline；活动 renderer app-path 含 `9.9.22-40824`；FileVersion 仍为9.9.19.35469 |
| 微信 | `C:\Program Files\Tencent\Weixin\Weixin.exe`；版本4.2.0.13，source=file_version，FileVersion 同值 |

版本字段保持各自来源，不用较旧 FileVersion 覆盖活动 app-path 证据，也不把候选目录直接当作运行版本。PID/HWND 只用于关联本轮日志，复跑须重新识别窗口、进程创建时间和归属，不可复用本文数值。

已授权的前台实验与后台任务标准分别判断：允许前台实验不表示后台路线可以先抢焦再恢复。`allow_foreground:true` 只放开工具的调用权限门，不提供阻止 provider 激活窗口的保护。已证明会抢焦的动作不能继续作为后台候选调用；可靠调用前防护缺失时保留缺口并推进其他只读路线。

| 证据 | 实际路径与边界 |
|---|---|
| probe.py、qq.py、wechat_keyboard.py 的界面调用 | `fastmcp.Client(server.mcp)` 进程内真实 MCP→server→真实 UIA worker→Windows provider；reveal等原生窗口入口按其实际实现执行。脚本的身份/进程清单另直接调用appinfo/Win32/psutil，不冒称这些元数据也经MCP |
| qq_guard.py | 原生窗口保护/前台事件观察，加真实 MCP 的搜索读取与写入；保护失败是负例，不是可复用防焦模板 |
| wechat_read.py / wechat-read.json | 一个独立诊断进程中直接调用 windows_mcp.uia、tree.read_detailed 和 oleacc/MSAA；**绕过 MCP/worker，不是新增 MCP 工具或 HTTP 测试** |
| test_see_transport.py | 真实 FastMCP 序列化，替换桌面执行与 worker 关闭；证明协议形状，不证明真实桌面效果 |
| http_ephemeral_check.py / http-ephemeral-check.json | 本次专属临时HTTP MCP服务→真实worker→无效hwnd参数校验；没有进入provider，也未重跑QQ动作 |
| qq_with_http.py / http-private-gui.json | 私有desktop中临时真实HTTP服务→该服务的真实受保护worker→QQ唯一selector→ValuePattern.Value→字符串投影；HTTP仅作此读取，搜索写入另走进程内MCP |

QQ/微信主要界面实验和QQ搜索写入采用上表中的进程内MCP路径；后续私有desktop内另验证真实HTTP的QQ Value读取成功链。临时HTTP与进程内调用均不等于验证已安装监听服务。独立 COM 进程的 269.97ms 与 MCP/worker 请求耗时包含不同工作，不作同路线提速比较。

## QQ：旧实例基线与实际重启条件

`qq-baseline-minimized.json` 记录旧主进程 PID1180、HWND4261960：最小化时 see 返回1元素、0命名，wall_ms=1670.6。`qq-baseline-shown.json` 中 reveal 后返回8元素、0命名，wall_ms=1686.5；timed_out=false、limit_reached=false、identity_complete=true。这是当前启动/状态下只读到窗口外壳的观测，不证明 QQ 没有 UIA。

旧 QQ 的主进程参数没有本轮三项参数。`qq-restart-flags.json` 保留正常关闭尝试及旧主进程终止记录（terminated=[1180]）；中间 inventory 已不再列出 QQ。随后 `qq-restart-flags-complete.json` 记录真正新启动的主进程 PID20892，并从运行进程参数核对：

```text
--force-renderer-accessibility
--disable-backgrounding-occluded-windows
--disable-features=CalculateNativeWinOcclusion
```

新 renderer 的参数也包含 CalculateNativeWinOcclusion，app-path 为活动 `versions\9.9.22-40824\resources\app`。不是只向已存在单实例重复发命令就假定 flags 生效。第二份记录的 terminated=[] 表示那次启动前旧 QQ 已不在进程清单中，不能抹去前一份实际终止记录。

launch 返回 PID20892、took_ms=5551、target_window_confirmed=false、visibility_control=not_requested、hidden_windows为空，前台前后样本保持6359280。因此不能把它描述为“已确认隐藏启动”；后续通过进程/窗口和 app_info 重新定位。登录窗口 HWND198676 读到28元素、6命名；现有账号登录后，新主窗口 HWND133284 的 `qq-main-initial.json` 返回312元素、128命名，wall_ms=3723.7，未超时/触及上限，identity_complete=true。

`qq-main-shown.json` 的已显示样本也为312/128，wall_ms=3442.9。其312项含182个Group、82个Text、18个Button等；当前遍历保留匿名可读节点，filtered_anonymous=0。此口径不与历史132/130或128/126直接相减。样本中的后台树可读不等于证明每个动作都能后台执行；下述 SetValue 已实际反证这种推广。

## QQ：同名拒绝与 selector 的边界

`qq-exercise-stable-selector.json` 在 QQ 非前台、微信前台的情况下，传字符串 target="更多"、读取 Legacy Name，返回 `ambiguous target`，detail 指明3个同名控件，execution_state=not_started、retry_safe=true；未将它降级成首个匹配或盲点。

其中2个同名控件为 ButtonControl；选定当前完整树中的目标后，以 `name + control_type + 当前rect` 作 AND 消歧，Legacy Name 返回“更多”。本次 rect 为 `[13,986,34,34]`，只是当前元素元数据，不是坐标点击入口，也不是可复用常量。精确查询 wall_ms=1965.1、took_ms=1962.6，前台前后均为微信；精确 selector 本身仍进行了定位，不能把它说成免遍历的快速直达。

搜索实验也保留失败：`qq-exercise.json` 中 Value 写入成功后，依赖旧名称的 selector 读回及恢复均出现 `no such control`，search_restored_exactly=false。不能把定位失败解释为写入未发生，更不能当作已恢复。后续 `qq-search-recovered.json` 重新读当前树、确认只有一个 ComboBoxControl，以该已核验唯一控件定位，读到探测值后恢复并读回，search_restored_exactly=true。中间搜索后的观察又可见通用名称“搜索”；记录只支持当时旧Name定位条件失效，不断言此名称永久变成了输入内容。

稳定运行采用 `{"control_type":"ComboBoxControl"}`，前提是当前完整树中恰好唯一；这不是建议任意页面都只按类型选控件。Name、rect、AutomationId 均可能随状态变化，定位失败必须重新观察，不能删除条件后直接重放未知结果的写入。

## QQ：搜索成功、抢焦与恢复

稳定运行的 search_original 先读取 Value，返回值仅在本机记录中保留长度/摘要，不公开原内容。写入的是专用探测串，非消息发送；后续 Value 读回与探测值一致，setvalue_effect=true，搜索视图327元素、133命名。实际行为是 **ValuePattern.SetValue 写入生效，同时前台从微信 HWND198862 切到 QQ HWND133284**，foreground_changed=true。

| 步骤 | wall_ms | took_ms | 观测 |
|---|---:|---:|---|
| 原值只读 | 1957.2 | 1954.8 | 微信保持前台 |
| type_text → uia:setvalue | 2491.6 | 2487.0 | effect_verified=true；QQ夺取前台 |
| 独立Value读回 | 1730.4 | 1727.9 | 与探测值一致 |
| 搜索结果视图验证 | 1885.0 | — | 327元素、133命名 |
| 恢复前再读当前值 | 1858.4 | 1855.9 | 保留当前状态核对 |
| 恢复原值 | 2344.7 | 2342.3 | 写入并读回匹配 |
| 独立确认恢复 | 2407.6 | 2404.7 | search_restored_exactly=true |

写入与独立Value验证合计4222.0ms；再含搜索视图验证为6107.0ms。原值读取另需1957.2ms，恢复及其前后读取另需6610.7ms，表中7次请求共14674.9ms；这些不能从试验总成本中省去。每个动作请求内部还含当前selector定位，表中wall_ms已包含该请求的完整客户端耗时，不能再加一次相同的内部took_ms。进入这7步之前的身份/初始树/前台布置属于另列的准备成本，不包含在14674.9ms内。

首次恢复补救也发生前台变化，不能被写成“后台无副作用清理”。有广义前台实验授权只解释这次调用为何可执行，不使它满足后台标准。该路线应以 uses_foreground=true 保存；前台端点相等的其他样本也只支持所采样端点，不能证明中间从未改变。

## QQ：四轮 Legacy 页面导航的完整成本

稳定运行先显式使微信处于前台，再对 QQ 的“联系人/消息”按钮调用 `LegacyIAccessiblePattern.DoDefaultAction`，已有授权由 `allow_foreground:true` 表达。它未主动先将 QQ 切前台。每步随后以 see 读取树并核对通用页面标记：联系人页出现“好友/群聊”，消息页对应标记消失；没有打开或发送具体聊天。

以下 wall_ms 直接取 JSON；动作请求包含当前树唯一定位与 provider 调用，验证请求包含读取当前页面。**完整成本=动作请求wall_ms+验证请求wall_ms**，不只计 DoDefaultAction 的内部耗时：

| 轮次 | args | 定位+动作 wall_ms | 动作 took_ms | see验证 wall_ms | 完整成本 ms | 验证页元素/命名 |
|---|---|---:|---:|---:|---:|---|
| 联系人 | []（wrapper默认等待） | 2513.4 | 2511.0 | 1093.6 | 3607.0 | 156 / 45 |
| 消息 | [0.0] | 972.6 | 969.6 | 2036.6 | 3009.2 | 312 / 128 |
| 联系人 | [0.0] | 1938.4 | 1935.7 | 1092.7 | 3031.1 | 156 / 45 |
| 消息 | []（wrapper默认等待） | 1466.8 | 1464.0 | 1997.9 | 3464.7 | 312 / 128 |

四轮基础闭环共8个MCP请求，wall合计13112.0ms，均值3278.0ms。进入导航前的显式前台布置214.5ms、早先一次background_tree读取2014.6ms分别另记；现场截图/其他探索成本也不能冒充这些8次请求之内已统计。两轮联系人页还各做了两次ItemContainer探测，额外为2042.1ms与1966.6ms，不是页面动作成本。

四轮动作和验证都记录foreground_before=foreground_after=198862、foreground_changed=false，说明这些采样端点保持微信前台。它们没有全过程前台事件记录，也没有光标采样，不能据此证明不存在瞬时夺焦。当前只可称“本版本、本次四轮导航有效且端点未见变化”，不能升级为普遍无夺焦保证。

该组没有记录已生效的调用前防抢焦保护，因此按当前skill的严格门槛，也不能只凭这些端点观测标为“已验证合格后台闭环”。导航功能、目标调用时处于后台、全过程观测和有效阻止能力分别保存，后续受保护的新变体须独立验证。

默认等待与0等待每种每页仅一个样本，前后页面、树大小和运行阶段不同。不能只凭969.6ms动作样本宣称零等待更高效，也不能从这四轮确定统计稳定性或全局最佳路线。应先在同层、同任务范围比较完整成本，再决定路线。

## QQ：ItemContainer 探测并未取得列表

联系人页每次挑选当下真实Tree/List/Window候选（最多两个；无此类才考虑Document），以当前control_type和rect精确定位后调用find_items。四个结果均为 `pattern unavailable`、pattern_id=10019、cause_unknown=true、execution_state=not_started；provider_calls=0、returned_count=0、complete=false、snapshot=false。两个页面轮次的请求wall_ms分别为1039.0、1003.1，以及993.3、973.3。

这证明这些具体容器在当前获取路径未得到可用pattern，并保留原因未知。它不证明整个 QQ 未暴露 ItemContainer，也不证明容器没有项目或其他列表/导出/API路线都不可行。没有取得全部联系人名单；QQ的节点总数、页面标记和模式探测不能代替业务全量证据。

## QQ：失败的调用前保护试验

`qq-guarded-background.json` 记录独立保护负例。起点为QQ非前台，脚本核对主进程PID/创建时间/路径；尝试 LockSetForegroundWindow 时 acquired=false、error=5。随后保护范围仅覆盖已知可见且归属该QQ主进程的顶层窗口：记录中1个窗口原enabled=true，被暂时禁用。**锁未取得就不能称前台已保护；禁用已知顶层也不是renderer的完整防焦屏障。**

其SetValue请求wall_ms=2160.9，返回provider error，COM HRESULT=-2147220992、execution_state=unknown、effect_verified=false、retry_safe=false。同时前台端点从6359280变成133284，前台事件观察捕获该QQ主进程的renderer/主窗口事件（HWND1312852与133284）。这次有实际事件证据，不能以“工具没显式SetFocus”“顶层已disabled”或授权标志来否定抢焦。

随后Value仍等于原空值，未证明探测写入生效；再次读取及最终读取确认search_restored_exactly=true。窗口enabled状态已全部恢复，enabled_states_restored=true；事件观察已移除，observer_removed=true。未知执行状态没有被伪写为未执行，也未自动重放错误写入。

此保护组合失败，不作为未来后台实验的操作模板。已知SetValue抢焦而当前没有可靠调用前防护时，应跳过这条后台动作路线，保留负例，继续可用只读调查；如现有授权覆盖前台实验，仍需在后台候选已处理后按前台路线执行，不能用该授权冲淡后台约束。事后切回前台不等于防止过夺焦。

## 微信：根窗口、真实子窗口与 Ctrl+F

微信PID18716，顶层HWND198862，class=Qt51514QWindowIcon。MCP基线如下：

| 样本 | 实际目标/状态 | wall_ms | 元素/命名 | 结论 |
|---|---|---:|---|---|
| wechat-baseline-hidden | 尚未reveal的顶层 | 1664.6 | 0 / 0 | 未读到语义内容 |
| wechat-baseline-shown | reveal后的顶层 | 1646.6 | 1 / 1 | 只见Pane，不能作为会话内容 |
| wechat-baseline-content | 真实MMUIRenderSubWindowHW子窗口133444 | 1745.9 | 0 / 0 | 该子根未读到后代内容 |

三次均timed_out=false、limit_reached=false、identity_complete=true；已列出2个原生子窗口。树遍历完整只是当前provider/过滤范围的完整性，不代表业务内容已覆盖，也不能把壳或单个child的空结果推广为整个微信无能力。

`wechat-search-focused.json` 中reveal后Ctrl+F以真实MCP key工具返回ok=true、call_completed=true、effect_verified=false、took_ms=257.8。后续仍为1个Pane。前后两张本机PNG文件（wechat-baseline-shown.png和wechat-search-focused.png）大小均160154字节、SHA256完全相同：

```text
e27421a7681e5924d17fe76759bfa5e298c7e422b0c9821d307ca4579f6de0ce
```

它不支持搜索框已获焦点的结论，因此没有继续输入探测词或任何聊天文字。“按键发送返回成功”没有被当成业务焦点已验证，也没有以盲打填补语义读取缺口。截图不变不证明快捷键绝对未被应用处理；这里只能说缺乏足够结果证据。

## 微信：独立直接 COM / MSAA / listener 调查

wechat-read.json使用独立诊断进程，未经过server._worker_call。外层启动命令以subprocess设置45秒进程期限；脚本自身明确provider_call_hard_timeout=false，不能把单次COM属性调用写成拥有worker硬期限。它核对顶层实际Weixin进程，并只纳入同PID、IsChild成立的2个原生后代：Qt51514QWindowIcon子窗口133454、MMUIRenderSubWindowHW子窗口133444。

| 目标 | 直接UIA树 | Legacy | Value/Text/ItemContainer | MSAA OBJID_CLIENT |
|---|---|---|---|---|
| 顶层198862 | 1个Pane | 可读Role/State/ChildId，Value为空 | 均pattern unavailable、cause_unknown=true | accChildCount=2；两个窗口/客户区代理，无业务值 |
| 已验证子窗口133454 | 0个后代 | 同上，Value为空 | 同上 | accChildCount=0，accValue无值 |
| 内容子窗口133444 | 0个后代 | 同上，Value为空 | 同上 | accChildCount=0，accValue无值 |

三个UIA根均存在，FrameworkId为Win32，ProviderDescription记录微软MSAA/Annotation/HWND代理；这说明本次取得的是这些代理层，不能据此断言应用内部一定没有其他可访问来源。三棵树均未超时/触及上限、identity_complete=true，未将匿名节点过滤掉。

每个目标还临时注册该HWND UIA子树的StructureChanged listener，等待50ms后重读control/tree，再移除listener。注册成功、移除成功，短观测窗event_count=0；重读未增加业务语义内容。短时零事件不证明以后无事件，也未启用全桌面长期监听。每目标control/tree/MSAA/listener包围耗时如下：

| 目标 | control ms | tree ms | MSAA ms | listener+重读 ms |
|---|---:|---:|---:|---:|
| 顶层 | 22.37 | 10.66 | 2.25 | 72.94 |
| Qt子窗口 | 4.44 | 3.29 | 1.03 | 62.74 |
| 内容子窗口 | 4.43 | 2.67 | 0.86 | 61.11 |

整次total_wall_ms=269.97、completed=true。前台前后均6359280，但光标端点从[672,608]到[747,202]、cursor_changed=true；没有证据归因于此只读脚本，也不能隐去变化或宣传整个试验完全不影响用户。没有连续光标归因/事件证据时，仅保存原观测。

这次独立进程结果不等于MCP已实现直接MSAA、listener工具，也不证明可绕过当前工具权限。它保留为后续适配与应用调查的证据；没有取得聊天正文/联系人列表，不能写成微信路线已完成。

## 隔离 desktop：首轮失败与第二轮搜索闭环分别计证

`desktop-identity.json` 的独立身份试验exit_code=0：child当前desktop为本次新建的`WinMCPProbe_*`，input desktop仍为Default，isolated=true。父端前台前后均6359280、foreground_events为空；observer已移除、desktop handle已关闭。这证明本次child确实位于独立desktop，不能据此直接宣称QQ、renderer、UIA worker和异步动作也全部已验证隔离。

首轮`qq-isolated-desktop.json`记录QQ实际启动、登录及真实MCP主树读取：main_tree为310元素、129命名，wall_ms=2287.1。已核对的QQ窗口desktop均为本次独立desktop；父端input_desktop_changes与foreground_events均为空，前台端点相同。随后worker线程desktop身份核验得到0而断言失败，parent exit_code=1；没有进入搜索setter动作。此轮不能写成隔离写入成功，也不能删去核验就将缺失证据改成通过。

首轮仅关闭本次创建并核对归属的QQ进程树，isolated_qq_closed=true；事件观察与desktop handle均已清理。此处保留首轮失败和已取得的读取证据。

`desktop-worker-identity-v2.json`改由实际worker在调用前后自报desktop：PID32192、TID23112均在本次`WinMCPProbe_*`，input desktop仍为Default。刻意传入无效hwnd的请求在参数校验时返回not_started；它验证worker身份与隔离前置检查，没有实际provider或QQ动作。exit_code=0，父端前台端点未变、无前台事件，observer和job/desktop handle均已清理。

第二轮`qq-isolated-desktop-v2.json`及child记录真正的QQ搜索闭环：新主进程PID23964、主HWND985266；实际UIA worker PID15476、TID26700。29个实际QQ根/renderer窗口desktop核验均指向本次私有desktop，worker各请求前后自报也在同一desktop，input仍为Default。这些`_probe_worker`字段是本轮诊断插桩，不能写成新增公开MCP参数或通用worker接口。

主树309元素、128命名，搜索后326/132。此轮先对搜索控件执行了`LegacyIAccessiblePattern.DoDefaultAction`，随后`uia:setvalue`写入探测串、独立Value读回、读取搜索视图，再恢复原空值并独立读回。effect_verified=true、search_restored_exactly=true、completed=true；因此不能省略语义focus步骤而把它描述为已验证的“直接SetValue”路线。

| 第二轮步骤 | wall_ms | took_ms | 证据范围 |
|---|---:|---:|---|
| 原值读取 | 2233.6 | 2228.7 | 空值，仅本机保存值摘要 |
| Legacy语义focus | 2177.8 | 2173.8 | DoDefaultAction已完成 |
| uia:setvalue | 4806.2 | 4800.5 | effect_verified=true |
| 独立Value读回 | 2220.2 | 2216.5 | 与21字符探测串一致 |
| 搜索视图验证 | 2143.8 | — | 326元素、132命名 |
| 恢复前再读 | 1994.4 | 1991.9 | 当前值核对 |
| 恢复原值 | 4495.4 | 4492.4 | effect_verified=true |
| 独立确认恢复 | 2094.4 | 2091.4 | 精确恢复为空值 |

这8个请求合计22165.8ms，其中语义focus、写入、独立Value与视图验证为11348.0ms。先前launch/登录/初始树/主树4个已计时请求另需10507.8ms，全部12个已命名请求合计32673.6ms。desktop/job建立、进程与窗口归属检查、事件观察及退出未各自给出wall_ms，因此32673.6ms是这些请求之和，**不是完整隔离保护的端到端成本**；未计部分不能默认为零，也不能据此与旧Default桌面路线宣称提速。

父端input_desktop_changes为空，没有观察到切换至私有desktop；父端前台却从6359280变为65850，已识别事件主要归属Explorer PID11604，另有PID=0的未归属事件。不能写成整个Default桌面前台未变，也不能把未归属事件强行归因。已记录事件未归属本轮QQ进程，只支持本轮所记录范围。私有desktop中的worker前台样本为null，`null→null / foreground_changed=false`本身不是用户桌面保护证明；保护证据必须来自desktop/进程隔离、父端input desktop和事件记录。

第二轮isolated_qq_closed=true、exit_code=0，job使用kill-on-close，observer_removed、job_handle_closed及desktop_handle_closed均为true；但关闭job handle并不等于已查询到job活动进程数为零。第二轮自身不覆盖直接SetValue变体或Job活动归零，后续结果在下节独立记录，不倒填成该轮已取得的证据。

## 随 skill 交付的入口：真实 worker 预检与直接 SetValue

后续已交付[private_desktop.py](../../skills/windows-app-automation/scripts/private_desktop.py)与[qq_private_probe.py](../../skills/windows-app-automation/scripts/qq_private_probe.py)，操作步骤、准入条件和异常处理见[前台保护参考](../../skills/windows-app-automation/references/foreground-protection.md)。两脚本使用当前venv与仓库源码，前者负责本次新desktop/Job/观察和清理，后者负责真实MCP→worker的逐调用身份检查、QQ实例归属、唯一selector、搜索独立读回与恢复。它们是随skill提供的命令行入口，不是新增MCP工具；没有给生产服务增加自动隔离参数。

`package-identity-parent.json`首先记录随包入口的独立身份预检：真实worker PID31176、TID23692在私有desktop，session=1、window station=WinSta0，input仍为Default。`see(hwnd=0)`在参数检查时not_started，没有进入目标provider。runner completed=true且worker_closed=true，父端事件hook注册/移除成功、errors为空；59个input样本均为`1/WinSta0/Default`，前台端点均6359280，事件为空。配置采样间隔50ms，实际最大相邻间隔79.445ms，不写成严格每50ms连续保证。

`package-qq-direct-parent.json`及其child记录无搜索预聚焦的直接setter闭环：本次新QQ与31个实际根/renderer HWND核验在私有desktop；真实worker PID32996、TID16660在每次实际分发前后核对同一session/window station/desktop和Default input desktop。主树309元素、128命名，完整、未超时/触及上限，搜索ComboBox恰好唯一。搜索步骤显式调用`invoke_pattern / ValuePattern.SetValue`，**没有先执行搜索语义focus**；独立Value读回与探测串一致，再核对当前值、恢复原空值并独立确认。登录当时使用通用click，实际fallback路由未保留，不能由搜索步骤没有键鼠调用推断整轮绝未使用键鼠。

| 随包直接setter轮次 | wall_ms | 观测 |
|---|---:|---|
| 真实worker预检 | 1719.1 | invalid hwnd，not_started，无provider |
| 启动本次QQ | 5564.5 | 本次新实例，原QQ存在即拒绝启动 |
| 登录树 | 232.8 | 28元素、6命名 |
| 已授权现有账号登录 | 688.5 | 通用登录按钮，未选择或公开账号 |
| 主树 | 2457.6 | 309元素、128命名 |
| 原Value读取 | 2064.5 | 空值 |
| 直接SetValue | 4575.2 | 调用completed；独立效果判断在下一步 |
| 独立Value读回 | 2003.4 | 与探测串一致 |
| 恢复前当前值核对 | 1946.0 | 属于本次探测值，未知并发值会拒绝覆盖 |
| 恢复原值 | 4444.1 | 调用completed |
| 独立确认恢复 | 2053.3 | 精确匹配原空值 |

搜索读写/恢复6请求共17086.5ms，写入加独立读回6578.6ms，所有11个已计时请求合27749.0ms。通用SetValue调用自身effect_verified=false被如实保留；runner依据独立读回另外判定effect_verified=true、search_restored_exactly=true，不能将两类字段混作工具自动提供的验证。此轮没有另读搜索结果树，只证明字段写入与恢复，不证明完整搜索结果或全部联系人覆盖。

外层helper从保护建立到runner结束及清理的lifecycle_ms=32957.268，其中preparation_ms=14.009、cleanup_ms=1.399，runner_wall_ms=32468.1；这些是嵌套计时，不能再次相加。lifecycle覆盖本次helper运行中的保护、启动、worker、登录等待、定位/动作/验证、恢复与结束，区别于只相加请求的27749.0ms。独立身份预检的另一次lifecycle为3566.870ms；若按指南先运行该独立预检再运行QQ轮次，两次helper生命周期合36524.138ms。外部授权、预先关闭旧QQ、Python入口前的启动开销不在这些计时范围内，不能算作零成本。

直接setter轮次父端532个input样本均为`1/WinSta0/Default`，最大相邻间隔72.463ms；input_desktop_changes为空，desktop_switch_observed=false。前台端点均6359280；observer installed/removed=true、errors为空，记录到的foreground/focus事件为0。未采集连续鼠标轨迹，不据此承诺光标不受任何因素影响；短暂desktop切换或事件遗漏仍以实际观察范围为限。

runner报告completed、effect_verified、search_restored_exactly、isolated_qq_closed、worker_closed均为true。外层退出时TerminateJobObject请求后保留Job句柄查询，实得cleanup.active_processes=0、cleanup.complete=true、errors为空，才释放本次资源，runner_exit_code=0、helper ok=true。该归零证据覆盖本次Job成员和普通后代，不能靠runner中isolated_qq_closed单字段替代；相关窗口/worker保持隔离直到本次执行环境结束。

此机制的可复用范围是已核验留在该非输入desktop的窗口的普通激活路径。它不是安全沙箱，不承诺阻止同权限程序显式切desktop、其他实例/外部broker接管或未知Job外工作。脚本拒绝既有QQ，逐次核对真实worker与目标窗口，变更版本/session/实例条件需重新预检；不能把单轮成功推广为所有应用、方法或统计稳定性。首轮失败、v2带focus变体及用户桌面上的旧SetValue抢焦记录继续保留，旧路线uses_foreground=true不改写。

上述成功样本之后的审阅发现runner原失败路径缺口：setter结果unknown时finally可能再发恢复setter，且恢复异常可能覆盖原错误。原成功路径不能覆盖该分支。修复后，通用call遇unknown/queued或guard身份不成立会阻断后续调用；setter还要求execution_state=completed且call_completed=true。无法确认完成或保护持续时不再读/写搜索状态，记录restoration_skipped并交本次Job终止；首个错误保留，provider/after-guard/worker-close等次生错误另存，不用清理异常覆盖根因。相应离线用例验证这些分支，未在真实QQ上故意注入未知写入来制造新副作用。

`package-qq-final-parent.json`用当时已修复unknown分支的runner再次完成真实直接SetValue闭环，未先执行搜索focus；该轮登录仍为通用click，后续登录路径修订另行验证。真实worker PID33436、TID35432调用前后归属均通过，最终保存的31个QQ根/renderer HWND核验均在本次私有desktop；已知窗口PID为21096、32520、33444。主树308元素、127命名，仍为完整唯一搜索控件；节点数与旧轮309/128的差异不作为功能退化或固定验收标准。

| unknown分支修复后那轮搜索闭环 | wall_ms |
|---|---:|
| 原Value读取 | 2112.4 |
| 直接SetValue | 4592.4 |
| 独立Value读回 | 2322.7 |
| 恢复前当前值核对 | 2001.6 |
| 恢复原值 | 4793.8 |
| 独立确认恢复 | 2071.5 |

这6请求共17894.4ms，写入加独立读回6915.1ms。另有真实worker预检1918.5ms、启动5592.0ms、登录树264.7ms、登录726.1ms、主树2335.5ms，全部11请求合28731.2ms。外层lifecycle_ms=34009.727、preparation_ms=13.509、cleanup_ms=1.262、runner_wall_ms=33524.2，分别保留各自计时范围，不能相加。最终effect_verified、search_restored_exactly、isolated_qq_closed、worker_closed、completed均为true，无error；外层helper ok=true、runner_exit_code=0，cleanup.complete=true、active_processes=0、errors为空。

该轮549个input样本均为`1/WinSta0/Default`，最大相邻间隔68.405ms，无desktop切换样本；前台端点虽同为6359280，期间却记录23个foreground/focus事件，foreground_or_focus_changed=true。现场进程核验中13条归属msedge.exe PID3144、9条归属WindowsTerminal.exe PID8720，另1条PID=0无法归属；未观测到已知本次QQ PID事件。**不能把helper ok=true、端点相同或无已知QQ事件写成整个用户前台全程未变，未知事件也不能补归因。**本轮仍未连续采样鼠标。

前两次随包成功、HTTP扩展轮和unknown分支修复轮分开保留，不把一次无事件与另一次源码/清理证据拼成不存在的统一样本。统计稳定性、任意方法/应用以及Job外路径均未因此获证；该轮完整helper生命周期约34秒，也不能与不同任务范围的单个动作毫秒数直接比较。

后续审阅进一步发现existing_account_login使用通用click，而该工具允许的实现路线可能退回真实鼠标；旧随包日志未保留实际via，故不能承诺那些整轮都只用语义调用。新入口改为显式`invoke_pattern / LegacyIAccessiblePattern.DoDefaultAction`登录，禁止自动改用click/坐标/键鼠，并要求ok、execution_state=completed、call_completed=true；请求的pattern/method/target/args和响应pattern/method也加入脱敏日志。14项runner离线回归与20项skill回归通过，旧效果、事件和清理记录保留，不倒填为新源码的完整复验。

`package-qq-semantic-login-parent.json`及其child随后用当前入口完成整轮真实复验。existing_account_login明确是`invoke_pattern / LegacyIAccessiblePattern.DoDefaultAction / args:[]`，没有通用click；该请求完成证据成立，后续完整主树307元素、127命名与搜索闭环进一步证实登录已进入主界面。真实worker PID27112、TID2560逐调用身份核验通过，最终保存31个QQ根/renderer HWND归属在私有desktop，窗口已知PID23196、24400、29916。

| 当前入口语义登录与搜索复验 | wall_ms |
|---|---:|
| 真实worker无效hwnd预检 | 1741.9 |
| 启动本次QQ | 5595.7 |
| 登录树 | 266.1 |
| 显式Legacy.DoDefaultAction登录 | 703.7 |
| 主树 | 2659.8 |
| 原Value读取 | 2405.7 |
| 直接SetValue | 4644.0 |
| 独立Value读回 | 2269.2 |
| 恢复前当前值核对 | 2827.3 |
| 恢复原值 | 5010.7 |
| 独立确认恢复 | 2245.9 |

11请求合30370.0ms，其中6个搜索/恢复请求19402.8ms，写入加独立读回6913.2ms。完整helper lifecycle_ms=35660.522，preparation_ms=13.050、cleanup_ms=1.970已包含其中；runner_wall_ms=35152.4。效果、精确恢复、QQ关闭、worker关闭、completed均为true；外层ok=true、runner_exit_code=0、Job active_processes=0、cleanup.complete=true、errors为空。相比旧约34秒轮次，这次增加的是对当前显式语义登录入口的实证，不能从单轮差异宣称性能退化或提速。

父端576个input样本均为`1/WinSta0/Default`，最大相邻间隔73.683ms，无desktop变化/切换样本；observer装卸成功、errors为空。前台端点虽同6359280，期间33条事件分别现场核名为explorer.exe PID11604共19条、DeepSeek Harness.exe PID22828共9条、WindowsTerminal.exe PID8720共5条，未观测到已知本轮QQ PID事件；这仍不是整个用户desktop前台全程不变的证据。鼠标未连续采样，有限样本和普通激活范围不扩展为全部应用、方法或Job外路径保证。

## 真实超时清理：只证明本次 Job 终止

`check_desktop_timeout.py`另外运行无GUI夹具：runner在私有desktop中创建一个普通子进程，随后故意挂起；外层helper设置2秒deadline。`package-timeout-parent.json`正确保留ok=false、runner_completed=false、stage=runner的TimeoutError，helper CLI预期exit_code=1；包装验收脚本断言该预期失败和清理结果后exit_code=0。这不是QQ动作失败，也没有将超时伪写成业务completed。

该轮清理实查active_processes=0、cleanup.complete=true、errors为空，另以psutil确认本次runner PID31964和记录的descendant PID均已消失。lifecycle_ms=2059.687，preparation_ms=13.483、cleanup_ms=3.450已包含其中；35个input样本均为`1/WinSta0/Default`，最大相邻间隔67.259ms，未观察到desktop切换或foreground/focus事件，hook正常撤除。

这验证本次Job成员及普通后代在真实超时后的终止与归零，不证明任意QQ provider超时已取消、Job外broker结束或已提交业务被回滚。worker超时与目标应用异步尾巴仍按各自范围处理，不能用这个无GUI夹具给所有未知provider调用补上“可靠取消”保证。

## 能否查看或接管私有 desktop

当前实际交付的是JSON运行证据：阶段、树类型/数量、值长度/摘要、真实worker与窗口归属、输入desktop/前台事件和清理结果。没有实时预览面板、远程桌面或人工接管工具。随包runner读取see响应后仅保留脱敏摘要，未保存私有desktop画面；已有按HWND的PrintWindow截图实现并不等于本轮已经验证QQ私有desktop图像正确、持续更新或可供人观看。

只读画面预览可作为后续候选：在隔离环境取目标窗口图像，再在当前用户桌面展示；这与改变输入desktop不同。需要真实验证应用绘制、非空正确图像、帧时效、隐私及捕获/传输/展示成本。图像为空或旧帧时记为该条件受限，不能切到实验desktop后截图再声称整段后台。本文没有为尚未实现的面板编造入口或成功记录。

显式SwitchDesktop可以作为直接查看/接管的实现方向，但会切换接收用户输入的desktop；这将占用当前输入环境并使原后台保护前提失效。本轮helper没有调用它，且结束时清理Job成员和自有desktop句柄，不保留可稍后打开的工作会话。未来若用户需要接管，需先停止新增自动化、查清在途动作和恢复责任，再按前台层实现切入/切回与异常清理，不能拿当前结果作已实现保证。

已验证的QQ字段语义读写能留在非输入desktop完成，不证明所有前台操作都可照搬。原生消息、其他UIA方法各自实测；SendInput和真实鼠标键盘没有本轮已验的目标HWND隔离路线，当前key工具的前台条件也没有因此取消。安全desktop/UAC和其他session未测。本报告不把私有desktop称为通用前台操作模拟器，也不从“在普通前台有效”推出“在此处后台必定有效”。

另建Windows交互会话或虚拟机只列为更重的候选，尚未实现或验收；其输入、渲染、权限与资源条件需另行验证。

## see 协议修复与验证

现场发现see的文本返回形状不能依截图有无而变。修复后，无截图、worker错误、非法worker结果均返回一个显式TextContent，客户端对首块文本一次JSON解码即得对象；有图时仍为同形状的metadata文本块加image块，并保存真实worker前台采样。

[test_see_transport.py](../../tests/test_see_transport.py) 使用真实FastMCP客户端，替换桌面执行，覆盖上述四支。修复前3个相关分支失败，修复后4项通过；随后本轮完整单元输出记录为317项通过。这证明协议回归通过，不把mock桌面执行写成真实应用无副作用证据；后续skill测试变更若增减总数，由最终验证另行记录。

登录语义路径修复及回归补齐后，当前源码最终全套命令为`& "$env:LOCALAPPDATA/winmcp/.venv/Scripts/python.exe" -X utf8 -B -m unittest discover -s tests -q`，实得356项、14.287秒、OK；skill的quick_validate另返回valid。输出仍有既有FastMCP弃用提示和mock socket ResourceWarning，不当作失败，也不将通过数回填为早先317项阶段的结果。离线回归与上述真实provider/HTTP/Job各自证明其范围。

另以`http_ephemeral_check.py`启动本次专属HTTP服务PID35052、临时端口52702。`http-ephemeral-check.json`记录tools/list共16项并含find_items；真实HTTP调用`see(hwnd=0)`经真实worker，在provider之前返回invalid arguments、execution_state=not_started。首个文本块一次JSON解码为dict，前台端点均6359280；该错误路径没有目标provider副作用可供验证。临时服务及其worker按本次归属精确清理，owned_processes_closed=true，命令exit_code=0。

初次面向已安装端口8765的`http_check.py`握手失败，随后原生TCP清单核对未见该端口监听。本轮没有部署、重启或验证已安装8765服务；临时HTTP错误路径成功不能替代这个缺失，也不能把进程内QQ搜索写成已通过HTTP验证。

随后`qq_with_http.py`在另一次私有desktop完整QQ闭环中附加了独立HTTP只读验证。`http-private-gui.json`记录16工具且含find_items；实际请求在HTTP服务的后代worker PID15864、TID18788中，按唯一`{"control_type":"ComboBoxControl"}`完成定位→ValuePattern.Value→字符串投影。调用wall_ms=3525.1，execution_state=completed，取得空值只保存长度0与SHA256；真实worker调用前后自报`1/WinSta0/WinMCP_*`、input为Default，服务后代归属核验通过。

该HTTP读取成功链不拼接前一错误路径；自身拥有真实目标、真实worker、成功返回及专属HTTP进程清理，owned_http_processes_closed=true。同轮搜索写入/读回/恢复仍走随包runner的进程内MCP路径，不冒称HTTP setter。`package-qq-http-parent.json`整轮lifecycle_ms=40027.980、preparation_ms=13.992、cleanup_ms=1.607，三者为包含关系；runner_wall_ms=39563.4。Job实查active_processes=0、cleanup.complete=true、errors为空、runner_exit_code=0、helper ok=true。645个input样本全为`1/WinSta0/Default`，最大相邻间隔70.987ms，父端前台端点相同、事件为空、hook正常移除；鼠标未连续采样。这个结果覆盖临时受保护HTTP getter成功链，仍没有验证已安装8765服务，也不证明任意HTTP动作或应用都已覆盖。

## 收尾时的普通 desktop 状态

私有desktop实验结束后另行恢复普通Default桌面的QQ；此阶段不计入35.7秒保护生命周期，也不作为后台保护证据。`qq-normal-desktop-restored-final.json`记录新root PID23436、启动5545ms，launch ok=true，但target_window_confirmed=false、visibility_control=not_requested。随后定位到登录页HWND1575920，`qq-normal-desktop-login-final.json`保留28节点登录树；现有账号登录明确返回route=uia:legacy-default、ok=true、execution_state=completed、call_completed=true，took_ms=683.5。其后身份清单出现QQ主窗口HWND1313406（1920×1032）与新renderer，支持已完成此次登录调用并产生主窗口。

末次`qq-normal-desktop-main-final.json`只读检查时，该主窗口已最小化（矩形坐标-32000），树仅1个Pane；没有再reveal或搜索来抢回前台，因此不声称完整主界面内容复验或原窗口布局已恢复。更早一次恢复只到登录页，最小化树缺少登录按钮而在动作前定位失败，不能算登录成功；最新上述结果与其分开保存。本轮执行者未关闭微信，但最新进程清单已无微信进程，原因未知，不能承诺微信始终运行或已恢复。

## 最终交接的源码与指南

最终交接时核对以下SHA256，交接稿§6.1内嵌正文与SKILL.md全文一致。安装须分发整个skill目录的入口、references与scripts；原始本机JSON不随skill安装，复跑产生自己的证据，不依赖本文PID/HWND。

| 文件（相对skills/windows-app-automation） | SHA256 |
|---|---|
| SKILL.md | `b930ef9b1eded5b7768857ead2ba7cf6e4fda9b30d7c7ffb4cedbef7a42d9e8a` |
| references/foreground-protection.md | `928ed6af3d6b6cb6e5cd3523820328ae096781e5f3065e94cdf96309b452b96c` |
| scripts/qq_private_probe.py | `bca364f81de1620fbafb610157f5c75b40ea70ccd3f731dbee6838b51371fcfa` |
| scripts/private_desktop.py | `a28f8f0766f91d6d4c478e8ba807b53a39df2eb7a79ff353188741502b81de8a` |

## 当前结论、保留工作与证据文件

四层路线顺序是后台高效→后台低效→前台高效→前台低效；效率只在同层、同任务范围内按完整成本比较。当前QQ后台树和Legacy导航具有上述有限实测证据；SetValue及失败保护例属于已观察到前台副作用的路线。允许前台实验、工具权限门放开、调用端点相同，都不能将后者重新包装为后台稳定方法。

QQ私有desktop变体已取得上述真实worker/窗口归属、语义闭环与Job终止证据，仍受版本、实例和普通激活范围约束，完整成本按各轮生命周期记录。微信的独立只读调查、实际child定位、MSAA与短listener已实际尝试；微信私有desktop、其他实际应用接口或后续微信试验仍未取得相应证据，不填成功、失败、总量或性能数字。UIA空壳、模式不可用和未验证搜索焦点分别保留，不能合并成“微信不支持自动化”。

本机还经真实remember以overwrite=false追加`qq@9.9.22 / live-search-ui-20261108`与`weixin@4.2.0.13 / live-provider-20261108`，两项返回ok=true、rank=0；脚本明确uses_foreground=true，保留上述抢焦与未知副作用边界。此操作未覆盖旧路线，也未将新观察升级信任；隔离成功变体须以自己的条件、成本与保护证据另记，不能继承无保护路线的分类。

`memory-private-recorded.json`另记录后续**只做recall的读回核验**，operation=recall_only_after_prior_remember：原`live-search-ui-20261108`的uses_foreground=true与新`private-search-20261108`的false并存，正文分别1211/2497字符、revision各自独立，两条均rank=0、reviewed=false、proven=false。先前remember已写入，其随后的读回因预算无效失败；本文件修正读回预算后仅查询，没有重复remember，也不是先前写入响应的替代品。该分类和低信任状态不能代替逐次身份/保护验收；新脚本版本与登录路径仍按独立证据核对。

`memory-semantic-recorded.json`再以独立plan `private-semantic-login-20261108`真实remember并逐plan以6000字符预算完整recall，revision为`ecfd595ab477fc6e8bfe065314561c1a40d0ca9fea1da155fb6fe4d7fb5d3ebe`，正文2723字符、next_body_offset=null，rank=0、reviewed=false、proven=false。uses_foreground=false只描述本轮已验普通激活路径；正文明确旧通用click登录分支证据不足和当前显式语义登录的实证，不能升级为全应用、键鼠或任意provider保证。旧`live-search-ui-20261108`的revision `7159e7f35521a3f5607760b520f9d61a6ea4a1f8a160af130419ae4ad34a0dac`及`private-search-20261108`的revision `f87c8ed3a82d6f5bcad9ecdbcdfa5d722d0cb4c216ef5ba6fd5996d3ef5f3d26`核对保持原样，不覆盖历史分类或失败记录。

主要本机证据索引（路径均相对本轮原始目录）：

| 文件 | 对应证据 |
|---|---|
| inventory-before.json、qq-restart-flags.json、inventory-restart-intermediate.json、qq-restart-flags-complete.json | 旧/新进程、实际flags与启动归属边界 |
| qq-baseline-minimized.json、qq-baseline-shown.json、qq-new-instance.json、qq-login.json、qq-main-initial.json、qq-main-shown.json | 旧外壳、登录及新主界面 |
| qq-exercise.json、qq-search-after.json、qq-search-recovered.json | 首轮成功写入后定位/恢复失败及补救 |
| qq-exercise-stable-selector.json | 重名拒绝/消歧、稳定搜索读回与恢复、四轮页面闭环、ItemContainer结果 |
| qq-guarded-background.json | LSFW与禁用顶层防护失败、前台事件与状态恢复 |
| wechat-baseline-hidden.json、wechat-baseline-shown.json、wechat-baseline-content.json、wechat-search-focused.json | MCP根/child、Ctrl+F与未继续输入的边界 |
| wechat-read.json | 独立直接COM、MSAA、短listener与桌面端点观测 |
| http-ephemeral-check.json | 临时真实HTTP服务的16工具清单、真实worker参数拒绝与本次进程清理；未进入provider |
| memory-recorded.json、record_memory.py | 两条真实remember追加的版本/plan_id/rank返回，以及overwrite=false、uses_foreground=true参数 |
| memory-private-recorded.json | 先前写入后的仅recall核验；QQ旧无保护与私有desktop条目并存，独立revision、rank0且未review/proven；未重复写入 |
| memory-semantic-recorded.json、record_semantic_memory.py | 当前显式语义登录变体的真实remember与完整recall；低信任新revision及旧两revision保留 |
| qq-normal-desktop-restored-final.json、qq-normal-desktop-login-final.json、qq-normal-desktop-main-final.json | 普通Default桌面重新启动、已完成语义登录与新主窗口；末次最小化Pane限制，不证明完整内容或原布局恢复 |
| desktop-identity.json、desktop-identity-child.json | child独立desktop与Default输入desktop的身份探测 |
| qq-isolated-desktop.json、qq-isolated-desktop-child.json | QQ首轮隔离读取及worker desktop身份核验失败；未进入setter |
| desktop-worker-identity-v2.json、desktop-worker-identity-v2-child.json | 实际worker自报私有desktop；无效参数请求未进入provider |
| qq-isolated-desktop-v2.json、qq-isolated-desktop-v2-child.json | 第二轮语义focus后搜索写入、独立读回与恢复；父端Explorer前台变化和清理边界 |
| package-identity-parent.json及其child_out指定的child | 随skill脚本真实worker身份预检、session/window station/input采样与Job活动归零 |
| package-qq-direct-parent.json及其child_out指定的child | 无先行focus的直接SetValue、独立读回/恢复、11请求与完整helper生命周期、31 HWND和Job归零 |
| package-qq-final-parent.json及其child_out指定的child | 失败分支修复后同一同步语义闭环复验；34秒helper生命周期、31 HWND、23条用户desktop事件及Job归零 |
| package-qq-semantic-login-parent.json及其child_out指定的child | 当前显式Legacy语义登录入口整轮复验；11请求、35.7秒helper生命周期、31 HWND、33条用户desktop事件与Job归零 |
| package-qq-http-parent.json及其child_out指定的child、http-private-gui.json、qq_with_http.py、http_private_gui.py | 新一轮受保护QQ闭环与临时HTTP真实worker的Value读取成功链、归属及清理；不等于HTTP setter或安装服务 |
| package-timeout-parent.json及其child_out指定的child、check_desktop_timeout.py、desktop_timeout_probe.py | 真实2秒deadline后的Job终止、活动归零与runner/普通后代退出，未调用QQ provider |

原始JSON保留脱敏摘要和通用UI标签，原始截图仅留在本机，不嵌入公开报告。已有失败与未试方向不因新增成功样本而删除；本轮没有证明完整名单、整个用户desktop全过程前台不变或跨版本稳定性，未取得的预览、键鼠与微信隔离证据仍保留未知。
