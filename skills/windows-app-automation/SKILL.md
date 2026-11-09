---
name: windows-app-automation
description: Use when automating or probing Windows applications, including native controls, UIA/Legacy, Electron, UWP/WinUI, self-drawn interfaces and virtualized lists; when reads/actions fail; or when choosing an official API, CLI or export instead. 控制陌生软件、读不到界面、点击不生效、完整列表采集、自动化路线选择。
---

# Windows 应用自动化

本 skill 指导 DeskWeft 的路线选择、实际操作、效果验证和恢复。memory 保存按应用版本
可复用的路线；MCP 执行有界调用并报告实际状态。先确认当前客户端有哪些工具，
工具尚未实现时写明缺口；源码已有但旧服务/客户端未注册时标部署或重载缺口，
不能把文档里的候选能力当成已注册工具，也不为补工具擅自中断正在运行的桌面任务。

本文中的 HWND、selector、名称、页大小都是调用示例，执行前从本次现场取得真实值。
详细参数查 [工具参考](references/tool-reference.md)；需要调查隔离和防抢焦时，按触发点
读 [前台保护与随包执行入口](references/foreground-protection.md)。
历史反例见 [有条件的现场经验](references/observed-cases.md)，不是本次测量或跨版本保证。

## 接手一个任务：先取得足够信息，再发下一次调用

1. **定义结果**：用户要哪个应用、哪个页面的什么数据或动作？读取当前项还是全量？
   需要哪些字段？允许哪些窗口、前台、重启、文件或业务副作用？复用已有授权，
   不为同一范围重复询问；缺少信息只阻塞依赖它的动作，先做不依赖它的调查。
2. **核对身份**：用 windows 取 hwnd/pid/title/class，app_info 取 exe、版本和证据。
   隐藏窗口不在 windows 清单内，启动返回的 hidden_windows 可提供已归属窗口。
3. **读记忆**：版本确定时 recall("name@version")；未知时先查 recall("name")，
   将其他版本当候选，不能把较新安装目录或 file_version 自动当活动版本。
4. **选当前可行层**：按下节四级顺序；先核对调用前保护、权限、目标定位和工具契约。
   后台无保护时继续身份/接口调查或其他合格后台候选，不先激活窗口建立“基线”。
5. **完成最小闭环**：取原状态 → 唯一定位 → 调用一次 → 独立验证目标效果。
   修改搜索框等可逆状态时还要恢复和核验；发送、删除、提交不因测试目的变可逆。
6. **按结果推进**：未开始可纠正前提；调用可能已执行则先查状态。结果、覆盖或恢复
   未确认时报告具体 partial，不把一次空树、一个成功返回或一个卡住的循环当任务结束。

下面是第 2、3 步的调用形态；不是要求每轮重复读取全部元数据。

```json
{"tool":"windows","arguments":{}}
```

```json
{"tool":"app_info","arguments":{"hwnd":123456}}
```

```json
{"tool":"recall","arguments":{"query":"example@1.0"}}
```

检查 app_info 的 source/warnings 和实际活动进程。source=null 表示版本没有证据，
version=None 的观察写为 app@unversioned；该记录缺失不应借用其他版本的已验证结论。
recall 的 exact=false、继承和家族匹配都只用于探索，即使返回旧方案的高 rank 也不能升级。
正文有 truncated 时用同一 plan_id，传 body_offset=该方案返回的 next_body_offset 续读；
next_body_offset 是返回字段，不是输入参数。每片 revision 必须一致；
revision 变化就重新读，不能拼接两版步骤。reviewed/proven 不是本次业务操作授权。

## 路线顺序：先后台，再在同层比较完整成本

1. **后台高效**：全闭环保持用户输入环境，完整成本在合格后台候选中较低。
2. **后台低效**：满足同一后台约束但完整成本较高，仍优先于前台路线。
3. **前台高效**：需要或可能占用前台，已有相应授权，成本在合格前台候选中较低。
4. **前台低效**：需要前台且成本较高，作为有依据的后续候选。

只在同层、同任务范围、同正确性/覆盖率和可比环境比较。完整成本包括保护安装/核验、
准备、定位、worker/IPC、调用、等待/轮询、验证、恢复与清理；另记调用和全树次数。
区分一次性成本与暖调用，不把单次 Invoke 的耗时与另一条路线的全流程相比较。
没有用户阈值就记录数据和比较对象，不发明预算或毫秒线；精确 selector 也可能读全树。

降级理由须对应有根据的上层候选：不适用、保护缺失、权限不足、定位/能力缺口、
效果/完整性失败或可说明的试验成本。已有前台授权、一种后台方法失败、已有一条能用，
都不能替其他后台候选作结论。不要求穷举所有技术；达到任务标准后无需执行更低层。

仅在复杂、全量或优化任务维护路线台账，简单任务直接记录关键事实即可：

| 路线 | 适用条件/层级 | 已有结果与覆盖 | 完整成本/副作用 | 当前状态与下一步 |
|---|---|---|---|---|
| 明确工具与目标 | 版本、页面、flags、保护 | 原值/字段/唯一条目数与总数来源 | 保护到恢复的成本；观测范围 | 已验证/已试失败/未试/权限阻塞/工具缺口及降级理由 |

## 后台试验：调用前先阻止应用抢前台

allow_foreground=true 不是防抢焦保护，只满足工具权限门。白名单、Get 前缀、隐藏窗口、
禁用顶层、没有报错，也不是防抢焦能力。先抢焦再切回属于事后恢复；即使 before==after、
foreground_changed=false，也只是两个采样端点，不能证明全程前台未变。
已发生抢焦的路线记 uses_foreground=true，不能因用户允许实验就改写成后台成功。

执行潜在抢焦 provider 调用前，必须能回答：

- 保护机制现在是否已实现？哪个可检查状态证明它对本目标生效？
- 是否覆盖目标 root/renderer、实际 UIA dispatch worker，以及可能的 broker/单实例接管？
- 从定位/读取到效果验证、恢复和异步处理结束，保护何时失效，如何停止后续动作？
- 超时或 runner 失联时，谁处理本次拥有的进程、句柄和恢复，如何验证退出？

缺少这些依据时不发出潜在抢焦动作，包括已知抢焦的 SetValue/Invoke/SetFocus 和
副作用未知的 provider 调用。记录具体缺口，继续其他后台只读候选；每个候选仍核对
自身副作用和保护。可以先查窗口/进程身份、实际启动参数、代码/接口与已有日志，
不能用换成 getter 的办法绕过前提。全部合理后台候选受阻后，才在已有授权内明确降到前台。

观测用于核查，不替代预先约束。报告前台/鼠标事件或采样的覆盖、间隔及遗漏可能；
未观测写未知。queued、固定等待或一次状态不变，都不能证明异步已结束并可撤保护。

### 私有桌面的两条不同路径

| 需求 | 当前路径 | 操作前必须核对 |
|---|---|---|
| 需要查看/接管由 MCP 创建的桌面 | private_desktop status/create/show/hide/close | show/hide/close 都须已有授权且 allow_foreground=true；visible_desktop 才是实际输入桌面 |
| 在非输入桌面运行目标和真实 worker | 随包 launcher + runner，见前台保护参考的执行入口 | 先 identity 预检，再核对目标/renderer/真实 dispatch 归属、效果、恢复和 Job 清理；仅适用于该 runner 支持的任务 |

private_desktop create 只创建一个桌面，**不会迁移已有目标、服务 worker 或登录会话**；
把私有 HWND 交给仍在 Default 的服务不构成隔离。show 会占用用户输入桌面，也不是
后台预览；当前无通用只读预览面板。close 关闭自有句柄，不证明其中全部进程已退出。
切回失败时保留会话并报告当前 visible_desktop，查明状态后可重试 hide/close。

随包 QQ runner 拒绝已有 QQ 实例；不能为了满足它而关闭用户现有会话。
它的 identity/可逆搜索流程不是通用发消息脚本，也不证明真实键鼠或任意应用可隔离。
需要新实例时复用覆盖启动/关闭和实验的既有授权，先按参考执行身份预检；不满足就保留
工具缺口，继续适用于现有目标的其他通道，不静默重启或切桌面。

## 观察与定位：先区分读不到的原因

具备本次读取的保护和适用依据后，先取得一份有界现场数据：

```json
{"tool":"see","arguments":{"hwnd":123456,"with_tree":true,"timeout_ms":3000,"max_elements":600}}
```

依次检查：

1. hwnd/pid/class/page 是否仍是目标；隐藏、最小化和宿主窗口是否影响读法。
2. timed_out、limit_reached、identity_complete 和 tree_diagnostics：空树与不完整树不同。
   有界读取不完整时，不凭已有半棵树判唯一；缩小到已核验的内容 HWND 或有据调整预算。
3. native_children 是否已有真实 Button/Edit/RichEdit 等独立句柄；不要把渲染宿主当编辑控件。
4. image_unavailable 只说明截图不可用；elements 为空也不能独立判断整个应用无语义。
   分别调查过滤、provider 错误、启动条件和实际内容宿主。

选择目标时复制本次元数据，不编造 AutomationId、类型名或坐标：

- 组合 selector 的 name/automation_id/control_type/native_hwnd/rect 按 AND 精确匹配；
  rect 是屏幕 [x,y,width,height]，必须附加身份条件，不能单独靠它定位。
- control_type 保留 ButtonControl/EditControl 等原值；不替换成 Win32 class 名。
- click/type_text/scroll 保留旧字符串的唯一子串回退；invoke_pattern/find_items 的字符串
  采用各自精确解析。重名优先加入稳定语义字段，不选第一个、nth、最近或截图猜框。
- name 可能随文本变化，rect 也可能变化。动作/恢复前重新核对身份；条件失配时重新观察，
  不能删掉条件后取第一个同类控件。没有足够证据认回原目标就停止该动作。
- target obstructed 表示鼠标点归属不是目标窗口；不动猜坐标重试。需要置前时先满足
  层级与授权；语义路线也须先查原动作状态，不能把遮挡当已获任何操作许可。

## 可执行候选路线：按现场触发选择

每张操作卡都服从上述层级、保护和权限；编号不是必须跑完的固定顺序。

### 1. 已有原生 child HWND：直接读取已确认的文本或状态

**触发**：native_children 已列出任务对应的 Edit/RichEdit/Static，反复全树定位成本高。
**操作**：核对 child 的父窗口、class 和业务内容；对它使用托管文本读取。

```json
{"tool":"post_message","arguments":{"hwnd":123457,"msg":13,"wait":true,"max_chars":4096,"timeout_ms":1000}}
```

**验证**：检查 text、result、possibly_truncated，与同目标已知值或另一只读来源核对。
空文本可能是合法空值；不能据此更换到不相关控件。截断时检查长度和接口上限，不能称全文。
**转向**：不响应/无独立 HWND 则比较 UIA/Legacy 或导出。查询勾选/当前索引的数值消息见
工具参考；当前索引不是全列表，不猜未允许消息，也不把查询升级为 setter 来试一下。

### 2. 根控件承载内容或目标重名：缩小定位范围

**触发**：已确认根或独立 child 承载目标属性；或多个同名控件需要消歧。
**操作**：只有前者可用 target="" 直接取根 pattern；后者从当前完整树组合精确 selector。

```json
{"tool":"invoke_pattern","arguments":{"hwnd":123456,"pattern":"ValuePattern","target":{"automation_id":"search","control_type":"EditControl"},"method":"Value","args":[],"allow_foreground":false}}
```

**验证**：返回值属于原业务目标；记录定位到读回的完整成本。目标没有 ValuePattern 时
比较卡 3，根控件空值不能推广为窗口无数据。selector 消歧不代表内部跳过遍历。
**转向**：无匹配、重名或 tree incomplete 时先重新观察；不能降成“第一个 Edit”。

### 3. Value/Text/Legacy 多种读法：核对字段和截断

**触发**：某读法只给标题、为空、慢，或正文边界不明。
**操作**：同一目标比较 ValuePattern.Value、TextPattern.DocumentRange.GetText、
LegacyIAccessiblePattern.Name/Description/Value；属性与 GetSelection 用 args=[]。

```json
{"tool":"invoke_pattern","arguments":{"hwnd":123456,"pattern":"TextPattern","target":"","method":"DocumentRange.GetText","args":[4096],"allow_foreground":false}}
```

**预期/验证**：GetText 返回有界正文，比较样本、字段含义、换行、长度和耗时。
possibly_truncated/result_truncated 任一为 true 就不证明全文；自动 TextRange 投影也有上限。
**转向**：当前 invoke_pattern 没有通用 offset；4096 是长度，不能改成下一页起点。
长度上限为 6001，且结果仍受投影预算约束（详见工具参考）；不能用 -1 请求全文。
先调查已存在的 range 导航、原生文本、Value 或完整导出。扩大读取长度仍不等于续读；
没有能覆盖正文的来源时交付已读前缀和具体适配缺口，不编造 body_offset。

### 4. 当前选择与表格结构：先分清覆盖范围

**触发**：任务涉及当前选中项、表格或只渲染部分行。
**操作**：Selection.GetSelection、SelectionItem.IsSelected 可读当前选择；Grid 的
RowCount/ColumnCount 可读规模。GetItem 的 args=[row,column] 已可表达，但当前不在
默认只读表内，需要其授权和保护，不能因为 Get 前缀就直接后台调用。
**验证**：选择集不是全列表；行列数不是已读完单元格。核对隐藏/筛选/标题行口径、
provider 是否只报已加载部分，以及返回 Control 元数据实际代表哪一项。
**转向**：需要逐项数据时进入容器/分页/导出路线；改变选择是另一项有副作用动作。

### 5. 虚拟化列表有容器能力：先建立两页闭环

**触发**：可见项目少于业务总量，或有 ItemContainer/Scroll/VirtualizedItem。
**操作**：先确认真正内容容器；ItemContainer 使用专用 find_items，从零开始。
多容器时传现场唯一 selector；空 target 可能选中第一个子容器，不证明它就是业务目标。

```json
{"tool":"find_items","arguments":{"hwnd":123456,"target":{"automation_id":"members"},"property_id":0,"value":null,"start_index":0,"max_items":100,"timeout_ms":8000}}
```

**验证**：检查 items、read_errors、metadata_complete、result_truncated、has_more、
next_start_index 和 reached_end。find_items 不 Realize、不滚动、不选择；返回的是 provider
序列，不保证已覆盖未渲染业务数据。某容器不暴露 ScrollPattern 不能推广为整个框架都不支持。
**转向**：pattern unavailable 且 cause_unknown=true 仍不足以证明 provider 不支持；先查
真实容器、包装能力和错误。查询无进展保留 partial，继续卡 6/7，不无限重复同一调用。

### 6. 内置搜索、展开、分页或分区导出：验证能覆盖目标范围

**触发**：滚动不前进，存在下一页/分类/筛选/搜索/导出功能。
**操作**：先读当前筛选与总数口径，保存原状态；在授权和保护范围内先验证两页或两分区，
检查新项目与页号/游标变化，再扩展。搜索/展开/翻页/导出仍是有副作用操作。
**验证**：分区是否穷尽、有无交叠、去重键是否可靠，导出的是当前页、已选、筛选结果还是全部。
未证明穷尽的关键词搜索只能找样本，不能证明全量；过滤恢复时不覆盖并发变化。
**转向**：一次无变化停止当前循环，核对容器/边界；其他合理方向仍可调查。完整性受阻就说明
已取得范围和缺少的身份/总数/稳定性证据，不因已经交付 partial 而宣称完成。

### 7. 官方 API/CLI、应用导出或已有浏览器接口：取得结构化来源

**触发**：需要大量精确字段、GUI 重复成本高，应用已有适用接口或输出。
**操作**：核对应用版本和官方接口/CLI/脚本、导出或已有合法浏览器语义/CDP 会话。
利用已授权来源，不因需要高效率就自行开调试端口、读私有数据库或扩张数据范围。
**验证**：来源、时间、分页/游标、字段、总数和样本一致；本地文件须确是本次完整输出。
请求、导出、解析与验证全计入成本。看到本地端口不等于 CDP，须有协议响应证据。
**转向**：接口不可用则记录具体能力/文档/权限原因，继续适用 GUI 候选；不反复猜端口。

### 8. UWP/WinUI 外壳为空：找到真正内容宿主

**触发**：ApplicationFrameWindow 只有标题栏/空 Pane，但存在应用内容。
**操作**：依据窗口/进程和 native_children 查 CoreWindow 或独立内容 HWND，核对归属后
在该 HWND 重新 see，再读对应 pattern。隐藏宿主不需要为定位而 reveal。
**验证**：内容字段与同一页面业务状态一致；标题相同不能证明不同 PID 属于同一目标。
**转向**：宿主无法认定时保留定位缺口；不猜跨进程窗口，也不把壳空当整个应用没有语义。

### 9. Electron/Chromium 后台树变空：按实际启动条件作对照

**触发**：同一目标失焦、遮挡后树缩小/消失；已确认框架和实际进程。
**操作**：先查活动命令行、窗口状态和历史版本条件。open_app(accessibility=true) 当前追加
--force-renderer-accessibility、--disable-backgrounding-occluded-windows 和
--disable-features=CalculateNativeWinOcclusion；传参不证明活动单实例已采用。
**验证**：同条件比较可定位任务字段、命名元素与重复读取，分别验证读树、动作效果和全量。
历史 QQ 的 flag 观察只是起点，不能把“通常可沿用”当新版本已验证。
**转向**：需要重启/新实例先核对授权、未保存工作和回退；不能按 PID 随便结束旧实例。
--disable-gpu、其他有文档依据的 feature、裸启动和 CDP 都是待按需验证的独立方向。
不堆叠未知 feature、不把重复同一 feature 计为新实验；某轮读树无变化不能推导 GPU 对滚动无效。

### 10. 自绘/空截图/动作无可见效果：比较独立证据

**触发**：Canvas/GPU 主界面缺少语义、截图空白，或 provider 成功返回但没看到变化。
**操作**：分开查 HWND/page、过滤/超时、原生 child、Legacy/其他实际属性、内置搜索、
快捷键和官方接口。登录页有语义不代表主页面有；一个控件类型失败不代表同窗口全部失败。
**验证**：PrintWindow 可能空白或缓存，帧相同不能判失败，帧不同也不能判业务完成。
优先核对任务相关状态；已有真实屏幕捕获可作为受授权的辅助证据，但像素差不等于业务语义。
**转向**：先按下节查原动作执行状态。需要鼠标时重新确认焦点、当前矩形、像素归属和授权；
截图不能自动产生可调用的坐标工具，工具缺口需明确报告，不能偷偷换全局输入兜底。

### 11. pattern、参数或返回值不能表达：定位具体适配缺口

**触发**：pattern not wrapped、result unsupported，或成员需要当前工具无法表达的类型。
**操作**：保存 pattern_id、成员、参数类型、真实错误与执行状态，核对当前包装/工具版本。
当前 args 支持标量及同一 HWND 内现场解析的 $control 描述，完整约束见工具参考；投影元数据
不是可回传的 COM 对象，列表内 null、跨窗口引用和任意对象仍不可表达。
若已注册工具的说明仍称只支持标量，先核对服务版本/源码与部署，按当前实际能力处理；
不能仅因 schema 允许任意 JSON 就假定支持，也不为探测支持度发起有副作用成员。
**验证**：$control 需要完整树中唯一匹配；可选 rect 只校验已唯一命中的元素，不能消除重名。
它不保存旧 COM 身份，不能证明同名替换元素就是原元素。ItemContainer 续项仍用 find_items。
**转向**：result unsupported 可能在执行后才发生，不自动重发；只记录缺口不等于获准改工具、
放宽权限或重启应用。有已可用路线时继续，不把“包装没实现”写成“应用不支持”。

## 读结果的顺序：执行到哪里、效果是什么、接下来能做什么

| 返回/证据 | 本次能说明什么 | 下一步 |
|---|---|---|
| execution_state=not_started | 工具报告动作未开始 | 纠正目标、权限或参数；核对现场后决定是否重新调用 |
| delivery=queued、execution_state=unknown、worker 超时/失联 | 可能已执行，尚不能判终态 | 停止新增副作用；保留保护，用独立只读状态查本次目标；不自动重发 |
| completed/call_completed/ok=true | 调用完成或送达 | 查业务效果，不把返回 True/False 当目标已经成立 |
| effect_verified=true | 工具验证了其声明的局部效果，例如文本读回相等 | 核对是否等于用户目标；写对字段不代表消息已发送 |
| captured frames are identical/differ，或旧版本 no visible change detected | 只说明捕获帧的比较结果或未观察到变化 | 结合 observation_source 查原动作；截图缓存、异步和不改变外观的动作仍可能发生 |
| result_truncated/possibly_truncated | 返回内容有界或可能不完整 | 按具体接口选续读方式；recall 有 body_offset，invoke_pattern 没有通用 offset |
| readback unavailable/budget exhausted | 写入可能已发生，但效果验证没完成 | 保留实际执行状态，查安全读回来源，不按失败再次写入 |

“没看到效果”与“确认未执行”必须分开。尤其发送、删除、提交、切换等可能不可逆或不可重复的
动作，只有可靠业务证据能确认本次目标未执行且不会延迟执行，才可决定重试。
retry_safe=true 也不是自动重试指令；先处理失败原因、当前身份和操作授权。
不要为得到一个成功标记而将同一业务动作依次交给 Legacy、Invoke、鼠标重放。

只有独立状态调查确认目标达成，才向用户说完成；无法判定就保留效果未验证，说明哪些已确认、哪些仍未知，
所需的具体观测或人工处理，不把 unknown 写成“失败所以再点一次”。

## 两个完整闭环示例

### 可逆搜索框写入与恢复

前提是已授权改变该搜索字段，目标与保护已核验；先用卡 2 的 Value 调用保存原值和目标身份。
若原值读不到，就不能承诺精确恢复；先处理这个缺口，不能默认原值为空。

```json
{"tool":"type_text","arguments":{"hwnd":123456,"target":{"automation_id":"search","control_type":"EditControl"},"text":"示例关键词","allow_foreground":true}}
```

1. 这是授权标记，不是后台保护；只有当前路线具备相应前提才调用。普通正文必须按字面输入，
   快捷键用 key；不能把正文中的花括号当键盘命令。
2. 检查 execution_state/delivery，再读同一字段，确认完整等于新值，并独立核对搜索结果。
3. 原值非空时也须完整替换，不能接受旧值+新值或只相等的前缀。不要用 Ctrl+A 后发 RIGHT
   来“预热”；若现场焦点不是目标字段，停止输入，不能以某个控件有焦点代替目标有焦点。
4. 原动作已确认结束、保护仍有效、当前值仍是本次写入值时，按同一精确目标写回原值并读回。
   若已是原值则不必再写；若出现用户/其他任务的并发值，不覆盖它，报告恢复受阻。
5. unknown/queued/超时先调查终态，不立即写回原值，也不假设杀掉 worker 就取消应用内异步。
   selector 的 name 变化时重新读完整树，证明仍是原字段后再读取；无法认回则不恢复。
6. 随包独占临时 runner 的 Job 清理只用于它拥有的进程，不能套到用户已有应用。

### 150 条列表的重叠分页与覆盖证明

假定业务总量 150 有独立来源；页大小 100 是本例参数。先用卡 5 读取 0..99，检查错误及截断，
在保持同一容器、筛选和保护的前提下读取重叠页：

```json
{"tool":"find_items","arguments":{"hwnd":123456,"target":{"automation_id":"members"},"property_id":0,"value":null,"start_index":90,"max_items":100,"timeout_ms":8000}}
```

1. 检查第二页索引是否为 90..149，以及 reached_end/has_more。两页交付 160 行，覆盖区间
   只有 0..149，不能直接加行数。每页都从 NULL 重扫，不是快照。
2. 对比重叠的 90..99，使用经验证稳定、范围内唯一的业务 id；runtime_id 可跨页变化，
   名称相同不代表同一人，不按姓名去重。AutomationId 只有现场证明业务身份后才可当键。
3. 相同区间不一致说明列表或顺序可能变化，不能强拼全量；在现有授权内重查必要重叠区，
   或调查稳定导出/API。没有足够字段区分同名项时，保留每行和这个完整性缺口。
4. has_more=true 且 next_start_index 前进才继续对应分页；没有更多、明确终点时检查覆盖。
   游标不前进、provider cycle、同页重复或一次滚动不变时停止该循环，保存 partial，换适用方向。
5. 后页 complete=false 是正常的后缀语义，不要求它变 true。声称全量须同时有业务范围/总数、
   连续覆盖、重叠一致、可信身份、终止边界和必需字段完整；complete=true 也不替代这些业务证据。
6. read_errors 单独保留：name/id 已读而 IsOffscreen 报错，不丢弃已读名单，也不隐去错误。
   结果截断则不能声称字段完整；已到序列末尾不证明未渲染项目不存在。

## 版本、证据强度与记忆维护

版本更新、页面/控件变化、新 renderer/worker、启动 flags、权限/session/desktop、
单实例接管或保护变化时，重新核验受影响前提。不要按最高版本目录选择活动版本，
也不要把旧版本一次成功覆盖成整个应用的规律。

| 证据 | 可用来做什么 | 不能代替什么 |
|---|---|---|
| 有条件的历史报告/候选 memory | 选择值得调查的方向 | 本次版本和效果验证 |
| provider 返回值、call_completed | 判断调用到达哪一步 | 业务完成、全量或无副作用 |
| PrintWindow/元素数/状态采样 | 辅助定位、排查和有界观测 | 真实屏幕新鲜度、业务效果、连续防抢焦 |
| 完整原值读回、任务相关业务标志 | 验证明确的局部或业务效果 | 其他字段、异步结束或整个任务的完整性 |
| 同轮保护→动作→验证→恢复→清理证据 | 支持本版本、本条件、本动作的复用 | 跨应用、跨版本或任意方法保证 |

一条 plan 保存一条能重现且可判断适用范围的路线；不要只记“可用/不可用”。先完整召回旧正文，
新增内容保留失败、未试方向和条件，测量过程/原始证据放报告，记忆保留必要事实与证据指向。
正文八节可按实际信息填，缺失写尚未记录，不猜测：

```text
## 目标
要得到的任务结果与字段/范围。
## 环境与适用条件
应用/版本证据、页面、目标、flags、保护与权限前提。
## 已验证步骤
实际调用、预期/实得、精确读回、恢复和终止条件。
## 已尝试但失败
真实输入、错误、影响范围；没调用不能记成失败。
## 实测记录
原始证据位置、覆盖、完整成本/调用次数、副作用及观测边界。
## 未解决
未达成目标、执行未知、缺字段或工具能力；下一步需什么。
## 未试方向
有依据的替代路线、预期、代价、回退和本次未试原因。
## 更新记录
新增、纠正、证伪和适用范围变化。
```

未知副作用写 uses_foreground=true，新方案 rank=0。受保护变体独立写条件，不继承旧路线的
后台结论；rank 不代表效率。用户确认 key/id/具体 revision 后才 approve；多次真实成功并
取得确认后才 confirm_proven。stale plan 要重新读取和确认，不能悄悄刷新 revision 继续审核。

整理过时方案时，先 remember 新方案并完整 recall 核对条件/失败/未试方向与 revision，
再用 forget 的 expected_revision 删除已被取代的旧方案。失败证据本身应保留；
空 plan_id 删除整个记录还需 confirm=true，不能为了瘦身先删后建或覆盖其他路线。

## 停止当前路线与交付

当前路线有未知副作用、定位失效、无进展循环或恢复受阻时，先停止该路线的新增动作，
保存状态与证据；继续不依赖该动作的安全调查。没有足够依据时不宣称用户任务已完成。

最终交付说清：完成了哪个范围、结果与完整性依据、是否恢复、实际前台/鼠标影响、
还缺什么及下一条可实施方向。仅复杂或优化任务附成本比较和路线台账，不把每次小操作
变成固定格式大报告。真实 GUI、HTTP 服务、离线模拟三类证据分别标注，不拼成一次成功。
