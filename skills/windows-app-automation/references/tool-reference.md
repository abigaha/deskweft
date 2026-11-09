# 工具参考：参数、返回值与已知缺口

本文件是 DeskWeft MCP 工具的**用法手册**，配合 [SKILL.md](../SKILL.md) 使用。
SKILL.md 给出可执行的操作卡和决策闭环，本文件补充参数边界与返回字段。先按主文核对
目标、保护和授权；下列“权限门允许”不表示 provider 保证不抢焦。

示例里的 `123456` / `123457` 必须换成现场已核对的 HWND；示例不代表该窗口一定暴露
对应能力。

## 一、本仓库工具契约清单（18 个，客户端以实际注册为准）

安装中的旧服务或未重载客户端可能少于此清单。先读现场工具名与 schema，区分“源码已有、
当前客户端未注册”和“工具尚未实现”；未注册时记部署/能力缺口，不编造调用。
更新服务或客户端需要按当前任务的授权和运行状态安排，不能为了补工具打断另一项桌面任务。

| 工具 | 作用 | 会动前台？ |
|---|---|---|
| `windows()` | 列出可见顶层窗口：hwnd、标题、类、pid、rect、foreground | 否 |
| `app_info(hwnd)` | exe、版本及版本证据来源 | 否 |
| `see(hwnd, with_tree)` | 截图；with_tree=true 加元素树、native_children、完整性诊断 | 不主动激活；UIA provider 仍须核对副作用/保护 |
| `click(hwnd, target)` | 点击唯一命中的控件 | 视路线 |
| `type_text(hwnd, target, text)` | 写入并读回验证 | 视路线 |
| `key(hwnd, keys)` | 真实键盘快捷键；正文用 type_text | 需授权，且目标实际持焦点 |
| `scroll(hwnd, target, direction)` | ScrollPattern 滚动 | 视 provider |
| `open_app(command, args, accessibility)` | 启动，尝试隐藏已确认归属的新窗口和恢复前台 | 无绝对保证；检查 foreground_preserved/still_visible/visibility_control |
| `reveal(hwnd)` | 把隐藏窗口放回屏幕 | **是**（需授权） |
| `find_items(...)` | ItemContainer 有界枚举，不显式滚动/Realize/选择 | provider 仍须核对；只读不等于防抢焦证明 |
| `invoke_pattern(...)` | 读/调用任意已封装 pattern 成员 | 视成员 |
| `post_message(hwnd, msg, ...)` | 原生窗口消息 | 视消息 |
| `private_desktop(action)` | 桌面的 create/show/hide/status/close | show/hide/close 需要前台授权；不会迁移目标/worker |
| `recall(query)` | 读记忆 | 否 |
| `remember(...)` | 写记忆 | 否 |
| `approve(...)` / `confirm_proven(...)` | 信任位 | 否 |
| `forget(...)` | 删除被取代的方案 | 否 |

### 常用控制：调用与结果消费

| 调用 | 参数与使用前提 | 返回后做什么 |
|---|---|---|
| `windows()` | 无参数，仅列可见顶层窗口 | 核对 hwnd/pid/class/title，不能把同标题当同一业务目标 |
| `app_info(hwnd)` | 已核验 HWND | 查看 exe/version/source/warnings；候选目录不是活动版本证据 |
| `see(hwnd, with_tree=false, timeout_ms=1500, max_elements=200)` | with_tree=true 才读取树和 native_children；timeout_ms 1..30000，max_elements 1..10000 | 分别检查 image_unavailable 与树的 timed_out/limit_reached/identity_complete/tree_diagnostics；树不完整不能按半树判唯一 |
| `click(hwnd, target="", allow_foreground=false)` | 当前唯一目标；明确原生按钮可走消息，否则需前台授权 | queued 只表示排队；语义调用完成也需业务验证，不能因无帧变化立即换路线重放 |
| `type_text(hwnd, target="", text="", allow_foreground=false)` | 替换该字段全部内容；保存需要恢复的原值。默认空 text 会清空字段，不能漏传正文 | 查 execution_state、effect_verified、verification_reason，并验证完整读回；正文按字面处理，不用于快捷键 |
| `key(hwnd, keys="", allow_foreground=false)` | 必须授权且目标实际位于可见前台；支持 Ctrl+s、^s、Enter 等键盘表示 | 按业务状态检查保存/导航效果；不能把成功注入按键当业务完成或安全可重发 |
| `scroll(hwnd, target="", direction="down", allow_foreground=false)` | direction 仅 up/down；使用 ScrollPattern，需要其权限与保护 | 比较 scroll_percent、effect_verified 与新增业务项；无 ScrollPattern 时该工具不会自动退回全局滚轮 |
| `reveal(hwnd)` | 没有 allow_foreground 参数，但调用本身须已取得展示/前台授权 | 检查 visible/is_foreground/ok；不把旧 HWND 或候选归属窗口直接揭示 |

字符串目标与组合 selector 的差异见主文定位章节；target="" 在 invoke_pattern/find_items
有根/容器语义，不能把其他工具的空 target 也当成“任取一个控件”。

### 启动与归属：不要把启动成功当后台保证

`open_app(command, args="", settle=2.5, show=false, accessibility=false)`。
command 与 args 是字符串；settle 是 0..120 秒数值。accessibility=true 追加当前实现的三项
Chromium 参数，show=true 表示不隐藏，不表示已取得一切前台动作的授权。

```json
{"tool":"open_app","arguments":{"command":"example.exe","args":"","settle":2.5,"show":false,"accessibility":true}}
```

仅在已有相应应用启动/改变运行状态的授权时使用，example.exe 必须换成已核对路径。
检查 pid、hidden_windows、window_candidates、target_window_confirmed、visibility_control、
foreground_preserved 和每窗 still_visible/hide_succeeded。应用可再次显示窗口，启动器只在
有界观察期内继续核验；调用结束后不持续监控。候选列表不是已归属列表，单实例接管时不能
关闭/隐藏原实例。前后采样相同也不证明全程未取前台。

### 记忆：读完整正文，写完核对，审核锁住 revision

| 调用 | 关键参数与结果 |
|---|---|
| `recall(query, max_body_chars=6000, plan_id="", body_offset=0)` | query 空只列 keys；精确 key、家族/继承和版本未知分别处理。正文预算属于整次响应；truncated 时按指定 plan_id 与 next_body_offset 续读，revision 变就重新读取 |
| `remember(app, version, plan_id, summary, cost, body, uses_foreground, overwrite=false)` | version=None 为未知版本；plan_id 最多 32 字符。覆盖需 overwrite=true，内容变化会清 reviewed/proven；保留旧失败与未试方向。返回 revision 后再完整 recall 核对 |
| `approve(app, version, plan_id, expected_revision, reviewed=true)` | 仅按用户明确确认过的同一内容/revision 设置或撤销 reviewed；stale plan 不能静默刷新摘要重试 |
| `confirm_proven(app, version, plan_id, expected_revision, proven=true)` | 多次真实成功且取得用户确认后标记；不是自动统计运行次数，也不授予执行权限 |
| `forget(app, version, plan_id="", expected_revision="", confirm=false)` | 删单条需旧 revision；空 plan_id 删整条记录还需 confirm=true。先核对替代方案已完整存好，不能先删后建 |

未定版本观察不能升 reviewed/proven。rank 是信任线索，不代表效率或本次操作许可。
recall 的 offset 是正文字符分页参数；不能把它复制给 invoke_pattern 的 GetText。

## 二、`post_message`：数值消息与参数

消息名只是给人看的，**`msg` 必须传整数**。查询用 `wait:true`（SendMessageTimeoutW）
才拿得到同步结果；`wait:false` 只返回 `queued`，消息还没到目标。

### 可后台执行的只读查询

| 查询 | 参数 JSON | 检查返回 |
|---|---|---|
| WM_GETTEXT (13) | `{"hwnd":123457,"msg":13,"wait":true,"max_chars":4096,"timeout_ms":1000}` | 返回 text；触及 `max_chars` 上限不能称全文完整 |
| WM_GETTEXTLENGTH (14) | `{"hwnd":123457,"msg":14,"wait":true}` | 长度不代表内容已采集 |
| BM_GETCHECK (240) | `{"hwnd":123457,"msg":240,"wait":true}` | 仅用于 Button class |
| CB_GETCURSEL (327) | `{"hwnd":123457,"msg":327,"wait":true}` | ComboBox 当前索引，**不是**全部选项 |
| LB_GETCURSEL (392) | `{"hwnd":123457,"msg":392,"wait":true}` | ListBox 当前索引，**不是**全部项目 |

`WM_GETTEXT` / `WM_SETTEXT` 走托管路径：服务分配并持有缓冲区，**调用方不传指针**。
`WM_SETTEXT` 会在同一时间预算内读回比较；`text readback mismatch` 才是写入不符，
`readback unavailable` / `budget exhausted` 只说明本次无法验证，不能自动重写。
max_chars 是可交付文本容量，不包含结束 NUL；possibly_truncated=true 时不宣称全文。

### 需要前台授权的消息（按效果判断，不按是否带指针）

`WM_LBUTTONDOWN/UP`、`WM_MOUSEWHEEL`、`WM_KEYDOWN/UP/CHAR`、`BM_CLICK`、
`WM_SETTEXT`，以及任何未知标量（还需 `allow_unsafe`）。

- 鼠标参数是 Win32 约定：按钮消息 lparam 用**客户区**坐标；滚轮 lparam 用**屏幕**
  坐标，wparam 高字是带符号滚动量。截图坐标要先换算。
- 一律拒绝：广播句柄、`WM_COPYDATA`、`WM_DROPFILES`、同进程窗口。

## 三、`invoke_pattern`：pattern 与参数

`invoke_pattern(hwnd, pattern, target, method, args)`。

- `target:""` 是**根控件直读**，不是"匹配空名字"或"选第一个控件"。只有确认根控件
  确实承载目标属性时才这样用。
- 非空字符串或组合 selector 必须在当前完整树中**唯一**命中，否则
  `no such control` / `ambiguous target` / `tree incomplete`，不动作。
- `args` 接受 bool / int / 有限 float / str，以及下述受控 `$control` 描述。
  `args:[]` 和 `args:null` 都表示无参，
  **不等于** `args:[null]`（后者会被拒绝）。

### 只读成员常用调用

| 查询 | 参数 JSON |
|---|---|
| Value 属性 | `{"hwnd":123456,"pattern":"ValuePattern","target":"","method":"Value","args":[],"allow_foreground":false}` |
| 有界正文 | `{"hwnd":123456,"pattern":"TextPattern","target":"","method":"DocumentRange.GetText","args":[4096],"allow_foreground":false}` |
| Legacy 名称 | `{"hwnd":123456,"pattern":"LegacyIAccessiblePattern","target":"","method":"Name","args":[],"allow_foreground":false}` |
| 当前选择 | `{"hwnd":123456,"pattern":"SelectionPattern","target":"","method":"GetSelection","args":[],"allow_foreground":false}` |
| 表格行数 | `{"hwnd":123456,"pattern":"GridPattern","target":"","method":"RowCount","args":[],"allow_foreground":false}` |
| 表格列数 | `{"hwnd":123456,"pattern":"GridPattern","target":"","method":"ColumnCount","args":[],"allow_foreground":false}` |
| 窗口显示状态 | `{"hwnd":123456,"pattern":"WindowPattern","target":"","method":"WindowVisualState","args":[],"allow_foreground":false}` |

Legacy 的 `Description` / `Value` 沿用 Name 示例，只换 method，保留 `args:[]`。
`DocumentRange.GetText` 的 maxLength 必须是 1..6001 的整数，不能用 UIA 常见的 -1
请求全文；返回字符串另受 6000 字符的投影预算约束。这个整数是**有界读取长度**，不是分页游标：满了、
`possibly_truncated` 或 `result_truncated` 为 true 时都不能声称全文完整。
`GetSelection` 返回的是当前选择，不是完整列表；返回的 Control 元数据不能当引用直接传回。

### 受控 Control 参数：现场重新解析，不保存跨调用引用

只在真实成员需要 Control 参数、当前包装已支持该成员时使用。例如某个参数的形态为：

```json
{"$control":{"hwnd":123456,"automation_id":"child","control_type":"TextControl"}}
```

- 外层仅有 `$control`；内部允许 hwnd/name/automation_id/control_type/rect。
  hwnd 必须与本次 invoke_pattern 的 hwnd 相同，并至少给一个非空字符串身份字段。
- worker 重新读取完整树；提供的身份字段按 AND 精确匹配，必须唯一。
  rect 若存在，只在唯一匹配后校验位置，不能用它消除多个同名项。
- 不接受裸字典、指针、跨窗口 Control、任意投影对象或列表内 null。
  它不保留原 COM 身份，也不证明同名同位置的替换元素还是原业务目标。
- 需要 Control 的成员仍按自身权限门调用；这种参数不是后台权限，也不是能力保证。
  ItemContainer 的 NULL 起点和连续引用继续交给 find_items 托管，不能用它伪造续项。

### 需要前台授权的成员

表外成员（`SetValue`、`Invoke`、`Close`、`SetFocus`、`Grid.GetItem` 等）必须带
`allow_foreground:true` 且已有授权覆盖。`Grid.GetItem` 读取第 0 行第 0 列：

```json
{"hwnd":123456,"pattern":"GridPattern","target":"","method":"GetItem","args":[0,0],"allow_foreground":true}
```

拿到一个单元格不等于拿到整张表。

### 报错要分清

| 返回 | 含义 | 能不能重试 |
|---|---|---|
| `pattern not wrapped` | 当前依赖没封装该 pattern（附 pattern_id） | 换路线或记适配缺口；**不是**应用没暴露 |
| `pattern unavailable` | 当前未取得该 pattern；cause_unknown 可能仍为 true | 检查容器、包装和实际错误；不能直接推广为应用不支持 |
| `result unsupported` | 类型还没做投影，**调用可能已执行** | 不得自动重试，记缺口 |
| `result_truncated` | 整体结果或 TextRange 投影被有界化 | invoke_pattern 没有通用 offset；调查真实 range 能力或其他完整来源 |

## 四、`find_items`：ItemContainer 查询

```
find_items(hwnd, target="", property_id=0, value=null,
           start_index=0, max_items=100, timeout_ms=8000)
```

它在**同一次 worker 调用内**持有 NULL 起点和后续元素引用，所以不需要客户端传
COM/Control 引用。它不调用 Realize、滚动、选择或焦点操作。

非空 target 从当前完整树中唯一解析。target="" 先查窗口根的 ItemContainerPattern；
根没有时，会有界遍历并选择找到的第一个子容器，**不保证容器唯一或属于任务**。
多列表页面优先传已核对的容器 selector；空 target 得到项目仍须独立核对业务归属，
不能把另一列表的终点或条数当目标列表的覆盖证据。树的 patterns 摘要不是完整能力清单，
未列 ItemContainerPattern 不等于容器不支持。

### 参数约束

- `property_id:0` 必须配 `value:null`，枚举 provider 的项目序列。
- 正 `property_id` 允许 bool / int32 / 有限 float / ≤6000 字符字符串。
  所有整数参数**严格排除** bool 和字符串数字。
- 范围：`property_id` 0..2147483647，`start_index` 0..10000，
  `max_items` 1..100，`timeout_ms` 1..30000。
- 常用属性：Name=30005、AutomationId=30011、IsSelected=30079。不支持的属性会报
  provider error，**不能**据此说容器没有项目。

### 示例（HWND 换成现场值）

| 目的 | 参数 JSON |
|---|---|
| 首批未过滤 | `{"hwnd":123456,"target":{"automation_id":"members"},"property_id":0,"value":null,"start_index":0,"max_items":100,"timeout_ms":8000}` |
| 重叠页检查 | `{"hwnd":123456,"target":{"automation_id":"members"},"property_id":0,"value":null,"start_index":90,"max_items":100,"timeout_ms":8000}` |
| 按名称过滤 | `{"hwnd":123456,"target":{"automation_id":"members"},"property_id":30005,"value":"Alice","start_index":0,"max_items":20,"timeout_ms":8000}` |

### 怎么读结果

- `start_index` 是**匹配序列**的偏移。每页都从 NULL 重扫、跳过前面的匹配项，
  所以后页不是上页引用的延续，也不是稳定快照。跳过的前缀**不会**交付给你：
  首 100 项加末 3 项仍然只拿到 103 项。
- 逐页检查 `items[].index` 是否连续、有没有间隙，用业务 id 去重。
- `runtime_id` 只用于**本次枚举**的身份/循环证据；虚拟 peer 重建时同一业务项的值
  可能跨调用改变，不能当跨页主键。
- `AutomationId` 只有经验证非空、范围内唯一且确实代表稳定业务身份时才能当跨页键。
  模板复用值、行位置编号不能默认当主键。
- `snapshot` 永远是 false。`complete` 只表示"从偏移 0 查到、provider 明确返回
  NULL 终点、元数据无错无截断"的**这一次查询序列**，不等于业务全量。
  后页即使 `reached_end=true`，`complete` 仍是 false。
- 出错时保留该项的 `read_errors`、`metadata_complete=false`，并区分"业务必需字段
  已读到"与"附加元数据缺失"：例如 name/id 已读而 IsOffscreen 报错，就保留名单
  并单独报告该错误，**不要丢弃已读名单或无限重试同一 getter**。
- `next_start_index` 不前进就停止重复查询，保留 partial 换方向。
- worker 卡死超时是 `execution_state=unknown`：不当成"应用没有容器"，也不自动重放。

## 五、已知缺口（当前不修，但要认）

| 缺口 | 影响 | 现状 |
|---|---|---|
| 不保留跨调用的 COM/Control 引用 | 只支持同窗口内以 `$control` 现场唯一解析 | 不能把返回元数据当缓存引用，也不能表达 ItemContainer 的 NULL 续项 |
| 通用 `args` 不能传列表内 null | 早期 ItemContainer 首轮/续项断路的原因 | 已由 `find_items` 专门解决 |
| 某些实测控件没有可用 ScrollPattern | 当前容器的滚动路线可能受阻 | 按版本和控件确认，继续真正容器、分页、搜索、导出等候选；不推广到全部 Chromium |
| 同一 API 在同一窗口内行为不一致 | 有的控件执行、有的假报成功 | 工具无法在调用前判断，只能靠效果验证 |
| 某些窗口 PrintWindow 返回缓存帧 | 捕获帧相同/不同不足以独立判断效果 | 优先读任务相关业务标志；现有真实屏幕捕获可辅助，也不能把像素差当业务完成 |

## 六、`private_desktop`

| action | 行为 | 需要授权 |
|---|---|---|
| `create` | 建一个独立桌面，**不切换任何东西** | 否 |
| `show` / `hide` | 把那个桌面切到屏幕 / 切回 | **是**（`allow_foreground=true`） |
| `status` | 只读 | 否 |
| `close` | 先尝试切回，再释放自有桌面句柄 | **是**（`allow_foreground=true`） |

- 返回的 `visible_desktop` 是**实际接收输入的桌面**（读自 OpenInputDesktop），
  不是本次希望的結果。切换被拒时会如实说屏幕在哪，不要当成功。
- 切换桌面不是沙箱：另一个桌面上的程序仍以你的权限运行，写的东西照样写盘。
- `show` 期间用户无法同时看自己的桌面；需要用户确认时先 `hide`。
- 这个能力解决"隔离后怎么让人查看/接管"，**不替代**调用前的防抢焦验收。
- create 不把现有应用或 MCP worker 移入新桌面；status 可用于检查当前会话。
- close 的切回失败会返回 closed=false 并保留会话；核对 visible_desktop 后再恢复。
  关闭句柄不代表关闭桌面上的全部进程，更不代表已取消应用异步动作。

## 七、返回字段速查

| 字段 | 说明 |
|---|---|
| `ok` | 本次调用没报错。**不等于**目标达成了 |
| `reason` / `detail` | 失败原因；区分未试、权限、工具缺口、provider 错误 |
| `execution_state` | `completed` / `unknown`（超时）/ `not_started` |
| `observation` / `observation_source` | 有限采样及其来源；无变化不证明未执行，PrintWindow 不是实际屏幕的新鲜度保证 |
| `route_effect` | 工具报告的局部观察；business effect unverified 仍需独立业务验证 |
| `retry_safe` | 明确未执行时才能安全重试 |
| `foreground_changed` | 两个**采样端点**的对比，不是全程监测 |
