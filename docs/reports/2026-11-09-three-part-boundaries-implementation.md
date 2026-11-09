# 2026-11-09 三部分职责重划实施记录

依据：[职责设计](../specs/2026-11-09-three-part-boundaries-design.md)。起点为
`a006941` 及已有的未提交实现；本轮保留这些改动，补查验收缺口。工作分支为
`codex/three-part-boundaries`。未提交、推送或部署。

## 实施范围

- skill 保留主流程、具体操作卡、参数来源、预期结果、验证、失败转向与恢复条件。
  完整参数参考和有条件的历史案例分别保存在随包 references，安装后可达。
- memory 继续存一条可重现路线的条件、步骤、失败、未试方向与证据指向；未改变存储
  schema，未整理或删除实际记录。缺失的 `app@unversioned` 不回退已知版本路线。
- MCP 保留执行结果与效果证据的区别，不自动匹配 memory、不将执行未知转成自动重放。
  源码注册的工具说明与当前实现对齐，源码通过不代表已安装服务已更新。

## 本轮发现并修复

| 缺口 | 失败证据 | 最小修复与行为回归 |
|---|---|---|
| 键入后的 Value getter 抛错丢失结构化结果；不匹配分支重复读回 | 两场景分别抛 `provider lost` / `read twice` | 只读一次，读回失败保留 `completed`、效果未验证、不可自动重试 |
| root PID 重用后误认无关子进程窗口 | 合成 launch 把无关 HWND 300 隐藏 | 快照后核验根进程创建时间；保留原父链检查 |
| SwitchDesktop 返回 true、读回未知或错误桌面后清空恢复路径 | `None` / `Other` 两场景错误返回 `closed=true` | 必须读回目标桌面；否则保留会话以便重试 |
| private_desktop 的 foreground_before 实际采在操作后 | 新回归得到 `22 != 11` | 使用操作前已有样本及操作后样本，删除只在事后连采的 helper |
| worker 启动异常漏 child socket，且未启动进程被误判存活 | socket fileno 未关闭；真实未启动 Process 的 join 使 `_unavailable` 非空 | finally 关闭 child；未分配 PID 时跳过 join，真实 Process 的连续两次调用均可重试 |
| 卸载误认多行字符串内的伪标题，或漏认引用/空白节名 | 隔离执行出现 `Unterminated string`；五种合法节写法残留注册 | 只以字符串、注释及数组外标题划节；精确区分大小写，识别引用和空白，保留相似服务器及父表 |

文档补齐：`DocumentRange.GetText` 的 `1..6001` 入参和 6000 字符结果预算；
`find_items(target="")` 的 root/首个子容器发现行为；启动隐藏与前台端点观察的局限；
create/show 不会把旧目标或 worker 迁入私有桌面；family recall 的 rank 属于返回版本。
README 中旧 QQ 数字保留为历史样本，不再表述为整个框架的保证。

## 当轮离线验证

解释器：`C:/Users/32677/AppData/Local/deskweft/.venv/Scripts/python.exe`（Python 3.14，
使用已有依赖，未安装新包）。系统 Python 缺少 MCP 依赖，不用其错误判定项目回归。

- 起始基线：`-X utf8 -B -m unittest discover -s tests -p 'test_*.py' -q`，
  454 项，25.359 秒，全部通过。
- 合并验证：同一命令，461 项，34.264 秒，全部通过。
- skill 的 `quick_validate.py`：`Skill is valid!`；`test_skill.py` 20 项通过，
  包括当前源码注册 schema 的调用示例检查和随包资源可达性检查。
- 新增行为回归均先复现失败再修复。卸载只在临时 USERPROFILE 中运行真实脚本，
  任务/进程系统接口使用隔离替身，没有执行真实卸载。
- 测试仍出现既有 socket ResourceWarning、FastMCP 字段弃用提示及故意输入错误的
  校验日志；它们未被隐藏，也未被当作测试失败。

完整测试输出及起始快照保存在本机 `.superpowers/sdd/2026-11-09-three-part-boundaries-design/`。
这是未提交工作的恢复证据，不随 skill 分发。

独立最终代码审查发现的启动恢复和 TOML 节身份两项均已修复，并通过限定复核。
[审查及复核记录](evidence/2026-11-09-boundaries/final-review.md)保留原失败与修复证据；
复核未发现离线交付阻断项。

## 独立操作者验证

[六情境完整记录](evidence/2026-11-09-boundaries/operator-scenarios.md)只依据当前分发
skill 和 references，不读测试预设答案，不调用实际工具：

| 情境 | 操作者决策 |
|---|---|
| 动作执行状态 unknown | 不重放；先获取独立终态证据，无法排除重复副作用时停止 |
| create/show 成功但目标/worker 归属不明 | 不宣称已隔离；先核验归属，停止依赖隔离的写操作 |
| 重叠分页含同名成员且无稳定 ID | 保留同名项，核对页间连续性与业务总量，不宣称全量 |
| GetText 截断且无 offset | 不编造续读参数；有界读/其他只读来源不足时停止全文声明 |
| 恢复前当前字段值与本次写入值不同 | 不覆盖并发修改；保留原值、现值与证据后停止恢复 |
| 键入 completed 但读回异常 | 保留已执行事实，仅独立读回；不把验证失败当成未执行 |

这是方法可执行性的离线推演，不能作为真实应用兼容性或恢复成功的证据。

## 本轮未执行

未运行真实 GUI 自检，未验证或重启已安装 HTTP 服务，未启动/重启/点击用户应用，
未进行 QQ/微信兼容矩阵或首字符现场复测，未写入、迁移或删除实际 memory。
真实应用效果及部署版本仍须依据后续当轮证据验收，不能用本报告测试数量替代。
