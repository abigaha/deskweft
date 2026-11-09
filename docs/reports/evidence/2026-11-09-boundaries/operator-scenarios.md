# 独立操作者情境验证

日期：2026-11-09。性质：只读文档后的离线决策推演，不是 GUI、HTTP 服务或应用兼容性实测。

本轮只以 `skills/windows-app-automation/SKILL.md` 及其直接链接的
`references/tool-reference.md`、`references/foreground-protection.md`、
`references/observed-cases.md` 作为决策输入；未读取测试里的情境答案。
下述调用未实际执行，未修改实际 memory。文档位置为本轮读取时的行号。

调用形态中的 `H` 为本轮已核验的顶层/内容 HWND，`C` 为已核验的原生文本 child HWND，
`S` 为本轮完整树里唯一、业务身份已确认的 selector；它们不是可照抄的示例数值。
每次读取都须沿用对应通道的保护和副作用前提。只读白名单不自动构成防抢焦证明。

## 1. click 或 SetValue 返回 execution_state=unknown

**实际决策：**停止新增副作用，保留已有保护；不重新 click、SetValue，不切换 Legacy、
Invoke 或鼠标重放，也不立即写回原值。unknown 表示原动作可能已经执行或仍会延迟执行。

**下一步具体调用：**先用不触发 provider 的 `windows()`，必要时 `app_info(hwnd=H)`，
核对已保存的 HWND、PID、class、title、exe、版本证据。窗口隐藏而未列出，不据此认定消失，
沿用已归属的隐藏窗口记录继续调查。它们只能确认身份，不能证明业务动作未执行。

- SetValue 的原字段有已确认的独立原生 child 时，下一次状态读取可为
  `post_message(hwnd=C, msg=13, wait=true, max_chars=4096, timeout_ms=1000)`。
- 没有原生 child，但同一目标的 Value 读取通道已经具备保护、实际 worker 可用时，可用
  `invoke_pattern(hwnd=H, pattern="ValuePattern", target=S, method="Value", args=[], allow_foreground=false)`。
  读取完整值并检查截断；只验证字段是否变成请求值，不能单凭这一点证明较早异步处理已排空。
- click 须读其任务相关业务状态，例如原任务已经定义的保存标记、搜索结果或展开状态。
  若现场尚无这个状态的 selector/原生句柄，先从受保护的
  `see(hwnd=H, with_tree=true, timeout_ms=3000, max_elements=600)` 取得完整性诊断和真实元数据，
  再选择实际存在的读法；不臆造某个业务 pattern 或“撤销/查询动作状态”工具。

**需取得字段：**原调用的 execution_state/delivery/reason、原请求内容与目标身份；当前
HWND/PID/exe/page；读取来源的可用性与保护覆盖；完整业务状态；异步已结束或可靠取消的依据。
worker 仍失联、实际 dispatch/保护未核验时，不把新的 UIA getter 当独立安全通道反复发出。

**停止条件：**没有安全独立读法、原目标无法认回、读回仍有截断或无法证明相关异步结束时，
保留“执行/效果未知”的 partial，并说明所缺业务证据。只在可靠业务证据同时证明未执行且
不会延迟执行后，才重新判断授权范围内是否重试。用户现有应用不因 unknown 被擅自终止。

**依据：**SKILL.md:23–32、77–97、124–143、281–299、317–320；
foreground-protection.md:99–108、219–228；observed-cases.md:10–24。

**文档不足/能力边界：**没有通用于所有业务点击的终态字段或异步排空接口；操作者仍需本应用的
业务证据。文档已说明缺口时应停止而非猜测，这不妨碍做出下一步身份调查或停止决定。

## 2. private_desktop create/show 成功，但 QQ HWND 与 worker 未证明迁入

**实际决策：**不在该 HWND 上继续发 SetValue/Invoke/SetFocus，也不称为后台隔离成功。
create 只建 desktop；show 改变实际输入 desktop，既不迁移已有 QQ，也不迁移旧服务 worker。
此时甚至不能假定当前私有 desktop 仍是“非输入”桌面。

**下一步具体调用：**

1. `private_desktop(action="status")`，读取实际 `visible_desktop` 和当前会话状态。
2. 用 `windows()` / `app_info(hwnd=H)` 核对现存 QQ 身份，不为取树先 reveal 或激活。
3. 若现有切桌面授权包含恢复且原动作已查清，使用
   `private_desktop(action="hide", allow_foreground=true)` 后再次 status 核对实际输入 desktop。
   hide 失败或状态不清时保留会话及真实状态，不循环 show/hide 来“试到成功”。
4. 需要调查另一条非输入 desktop 路线时，按 foreground-protection.md:267–280 的
   随包 `private_desktop.py ... qq_private_probe.py identity --repo ...` 命令预检。
   这是未来可执行入口，不在本轮运行；解释器、skillDir、repoDir 和输出路径须来自现场。
   identity 不启动 QQ，也不证明已有 QQ 已经迁移。

**需取得字段：**实际输入 desktop 的 session/window station/desktop 组合身份；目标 root、
内容窗、renderer 的 HWND→创建线程→PID 与 desktop；真实逐调用 dispatch 的 PID/TID、
调用前后 desktop；broker/单实例接管范围；前台保护、事件观测和清理责任。
identity 父报告的 `child_out` 指向本次子 JSON，还须核对父/子 completed、worker 归属、
`cleanup.complete`、`cleanup.active_processes=0` 与 errors，不能用旧同名 JSON 代替。

**停止条件：**任何目标/worker 归属缺失均不进入 provider 动作。QQ runner 拒绝已有实例，
不能为了使用它而关闭用户当前 QQ；只有没有现存实例且已有启动/关闭/可逆实验授权时，
才考虑文档给出的新实例 QQ 流程。现有实例不能隔离时记录工具缺口，继续适用于它的其他通道。
关闭 desktop 句柄不证明应用进程退出或异步动作已取消。

**依据：**SKILL.md:99–114；tool-reference.md:240–256；
foreground-protection.md:149–199、267–281、283–319、332–350。

**文档不足/能力边界：**MCP 没有“迁移现有 QQ/worker”或通用 desktop 归属探测工具；
随包 identity 只解决特定新执行环境的预检。文档把该界限与现有实例的停止条件写明了。

## 3. find_items 两页重叠，同名成员且没有稳定 ID

**实际决策：**保留两页每行、页来源、`items[].index` 和错误信息，不按姓名去重，也不把
跨调用 runtime_id 当业务主键。不同姓名可辅助比较，但不能替代同名成员的身份。
两页都是从 NULL 重扫，不是快照，不能仅凭重叠姓名相同证明成员没有替换或换序。

**下一步具体调用：**先离线核对现有两页的索引区间、交叠、间隙、筛选、
metadata_complete/read_errors/result_truncated、has_more/next_start_index/reached_end。
如果一次受保护的重叠区重查可以检验当前顺序是否已经明显变化，可用：

`find_items(hwnd=H, target=S, property_id=0, value=null, start_index=O, max_items=K, timeout_ms=8000)`。

`O` 必须来自两页真实重叠起点，`K` 为真实重叠范围内且 1..100 的数量，不能照抄 90/100
假定本现场页大小。这个重查只能发现某些不一致，不能凭空补出稳定身份。没有可检验的新证据时
不重复它，转查应用是否存在稳定业务 ID、分区导出或官方 API；不能为了得到唯一值编造字段。

**需取得字段：**两页的真实 items[].index/元数据/错误、相同容器与筛选证据、稳定业务身份
来源及唯一性/跨页稳定性、独立业务总数与范围、连续覆盖及明确终点。
AutomationId 只有经验证代表稳定业务身份才可用，位置编号或复用模板值不算。

**停止条件：**无稳定 ID 时停止“跨页去重并证明全量”的结论，即使 reached_end=true。
若继续采集样本是任务所需且游标前进，可保留原始行和索引继续有界读取，但结果始终标记身份/
覆盖未证实；游标不前进、provider cycle、同页重复或列表变化则停止当前循环。
已有必要字段的条目不因 IsOffscreen 等附加 getter 报错被丢弃。

**依据：**SKILL.md:203–227、323–343；tool-reference.md:177–228；
observed-cases.md:64–71。

**文档不足/能力边界：**find_items 不提供跨页稳定快照或自动业务 ID。文档足以指导保留同名行、
限定重查的证明力和停止全量宣称；具体完整导出接口仍需应用侧调查。

## 4. DocumentRange.GetText 返回截断，没有 offset

**实际决策：**当前输出只是前缀。没有合法的下一页 offset，不给 invoke_pattern 加 offset、
body_offset，不把第二次 GetText 的长度当起点，也不传 -1 请求全文。

**下一步具体调用：**若同一原目标已确认暴露 ValuePattern，并满足其读取保护，可比较：

`invoke_pattern(hwnd=H, pattern="ValuePattern", target=S, method="Value", args=[], allow_foreground=false)`。

若它实际上是已核验的原生 Edit/RichEdit child，可先用
`post_message(hwnd=C, msg=14, wait=true)` 查长度，再在 max_chars 1..65536 的工具范围内
选择能容纳全文及完整性判定余量的 `post_message(hwnd=C, msg=13, wait=true, max_chars=N)`。
内容仍在变化、触及上限或 possibly_truncated=true 时仍不能称全文。没有上述真实能力时，
先查应用已有 range 导航或完整导出/API，不臆造一个 range 分页工具。

**需取得字段：**原 pattern/目标身份、请求长度、result_truncated/possibly_truncated、
实际返回前缀与长度；替代源是否覆盖同一正文、是否也受投影上限影响、版本/时间与完整性依据。
GetText 接受的 1..6001 是长度，字符串投影另有 6000 字符预算，扩大长度不保证补齐正文。

**停止条件：**没有能覆盖全文的来源时交付已读前缀与适配缺口，不宣称全文，不循环扩大
GetText 长度伪装续读。替代 Value 返回截断同样受限，不能把换 pattern 当作完整性证明。

**依据：**SKILL.md:149–161、176–191、229–236、290；
tool-reference.md:79、86–99、122–138、168–175。

**文档不足/能力边界：**当前通用入口没有可照抄的长文本续读路线，也没有持久 range 引用。
文档准确给出长度上限、替代候选和交付 partial 的条件；要承诺全文仍须特定适配或完整来源。

## 5. 恢复搜索框前，当前值不同于刚写入值

**实际决策：**若当前完整值已经等于保存的原值，视为无需再次写回，再核对任务要求的状态。
若既不是原值也不是本次写入值，视为可能并发修改，停止恢复 setter，不覆盖用户/其他任务的值。

**下一步具体调用：**若当前读回已经完整且身份可信，不为制造成功记录重复调用或写入。
如果变化涉及 name/selector 失配，用受保护的
`see(hwnd=H, with_tree=true, timeout_ms=3000, max_elements=600)` 重新取得完整树和真实身份字段；
确认仍是原字段后才用
`invoke_pattern(hwnd=H, pattern="ValuePattern", target=S, method="Value", args=[], allow_foreground=false)`
重新读当前值。不能删掉旧 name 后不加证明地选第一个 Edit/ComboBox。

**需取得字段：**原值、本次写入值、当前完整值、原目标与当前目标的身份证据；原动作是否已结束、
保护是否仍有效、是否存在并发修改证据。保存与报告遵守任务隐私范围，不将搜索内容无必要扩散。

**停止条件：**当前值是第三种并发值、原目标无法认回、原动作仍为 queued/unknown 或保护失效，
均不执行恢复写入；报告恢复受阻及保留现状。仅当原动作结束、保护有效、目标明确且当前完整值仍
是本次写入值时，才按原精确目标写回保存原值并完整读回核验。

**依据：**SKILL.md:135–143、303–321；foreground-protection.md:205–215；
observed-cases.md:35–41。

**文档不足/能力边界：**无法归因第三种值一定由谁修改，也没有搜索框原子 compare-and-set；
文档选择不覆盖并要求说明受阻，已给出可执行的安全结果，而非要求操作者猜测归因。

## 6. 键入返回 completed，但 Value 读回抛错

**实际决策：**记录“键入调用完成，效果未验证；读回 provider 报错”。completed 不因为验证
失败而降为 not_started；不能重新 type_text、重发正文、Ctrl+A/Delete，也不能以重新写原值
来试探当前状态。不以错误后的截图不变证明没有输入。

**下一步具体调用：**先保存本次执行状态、route/delivery、verification_reason 与原目标身份。
存在事先核验的原生文本 child 时，使用
`post_message(hwnd=C, msg=13, wait=true, max_chars=4096, timeout_ms=1000)` 作为独立读回，
并检查字段完整性；存在另一个已核验的 Text/Legacy 来源时，按卡 3 的实际能力读取同一业务字段。
若只剩同一个会抛错的 Value getter，不无限重试它；先查安全接口/已存日志与 provider 错误范围。
身份可能失效时可先 `windows()` / `app_info(hwnd=H)`，受保护的 see 仅在实际 worker 和保护
仍有效时用于认回目标，不把它默认视为无副作用的独立证据。

**需取得字段：**execution_state=completed、effect_verified=false、具体 getter 错误；
当前字段身份及完整读回来源；请求正文完整相等而非匹配前缀；任务业务效果与相关异步终态。
如果只是搜索框文本一致，还须另查搜索结果；文本一致不证明其他业务任务已经完成。

**停止条件：**没有安全读回来源或无法认回原字段，保留效果未验证与恢复未确认的 partial。
取得完整独立读回后再按情境 5 的并发/恢复条件判断，仍不为了补一个成功标记重发输入。

**依据：**SKILL.md:176–191、281–299、303–320；
tool-reference.md:43–45、96–99、258–268；observed-cases.md:23–24、35–41。

**文档不足/能力边界：**没有承诺 getter 抛错后必有另一种能读回的接口。文档给出可用通道的
筛选办法、不能重写的条件和无法验证时的交付方式，足以在缺口现场停止而不扩大副作用。

## 方法可执行性判断

六个情境均能仅凭所读文档得出下一次合法调查调用、调用所需的现场字段、以及缺字段时的停止
条件；方法可执行性满足本轮这六个情境。这里的“满足”包括工具确实缺失时明确停止相应动作，
而不是保证所有应用最终都能完成。文档没有诱导我发明 offset、迁移能力、业务 ID 或动作取消接口。

仍需应用/环境实际证据才能完成的工作包括：unknown 的可靠业务终态、现有实例完整 desktop
归属、同名成员的稳定身份、长正文完整来源、并发变化归因和可用的独立文本读回。
这些是本轮文档承认的能力/证据边界；本推演不把它们标为现场已解决。

未执行任何 GUI/桌面输入、HTTP 服务调用、随包 runner、真实应用或实际 memory 操作。
因此没有真实兼容性、连续防抢焦、业务效果或恢复成功的新增证据。
