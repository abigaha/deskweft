# 最终独立只读审查（2026-11-09）

What this change does: 将 skill 的操作决策、memory 的有条件路线和 MCP 的执行/读回职责重新分开；同步修正输入、文本读回、进程归属、私有桌面恢复、worker 启动清理和卸载节删除。审查按单用户本地桌面服务的实际负载进行，重点核对授权、执行未知不重放、恢复和配置完整性。

审查范围：先读设计稿，再读 review-package.diff、当前相关实现与调用者、行为测试，以及未跟踪的 test_uninstall.py、tool-reference.md、observed-cases.md；另外核对了本轮最后修正的 server.recall docstring。未修改实现、测试或文档，唯一写入是本报告。

## Must fix（已处理 / addressed）

1. **真实 Process.start 异常仍会永久禁用所有 worker 工具**（`deskweft/uia_worker.py:392`，关联 `:431-441`）

   **状态：已处理。** 限定复核当前实现，`_reap()` 仅在 `proc.pid is not None` 时执行 terminate/join/kill；未启动对象仍会 close，child socket 的 finally 清理保留。独立重跑原边界的离线片段：两个真实未启动 Process 仅 mock start 抛 OSError，两次 call 均返回 not_started/retry_safe，实际执行两次构建，`_unavailable is None`，四个真实 socket 均关闭。新增回归使用真实 Process，已消除原 Mock.join 掩盖行为的问题。

   - **问题**：新增异常分支依赖 `_startup_reap()` 的 clean 结果决定是否允许重建。真实 multiprocessing Process 尚未成功 start 时，pid 为 None，`is_alive()` 为 False，但接下来的 `join()` 抛 `AssertionError: can only join a started process`；`_reap()` 把任何异常判成仍存活，导致 `_unavailable` 进入永久拒绝状态。此时实际没有待回收子进程。
   - **离线复现**：创建真实 `multiprocessing.get_context('spawn').Process(target=print)`，仅 mock 该对象的 `start()` 抛 `OSError('temporary spawn failure')`，并让 `_spawn()` 使用它；随后连续调用两次 `uia_worker.call('see', {'hwnd': 1}, 1000)`。两次均返回 `reason='worker unavailable'`，第二次没有重新尝试 start，`proc.pid` 仍为 None，`_unavailable` 非空。本复现未启动子进程或执行任何桌面调用。
   - **最小修复**：在 `_reap()` 内单独处理从未启动的 Process，关闭其对象资源后返回不存活；回归测试使用真实未启动 Process 并只 mock start，避免 Mock.join 掩盖标准库前置条件。已有 socket 两端关闭逻辑正确。
   - **不修的后果**：一次暂时性的 spawn 系统错误就需要重启服务，且返回 `retry_safe=true` 的重试永远不能恢复。该缺口来自旧 `_reap`，本轮新加的真实启动异常恢复分支仍受其影响；不是声称 socket 清理发生回归。

## Should fix（已处理 / addressed）

2. **合法 TOML 节名变体会留下残缺的 deskweft 注册**（`uninstall.ps1:46`）

   **状态：已处理。** 限定复核当前 header 身份匹配，支持 bare/basic/literal 键与点旁空白，并以 `-cmatch` 保留不同大小写键。独立只运行字符串处理片段，五种引用/空白变体及嵌套 env 均完整删除；tomllib 核对父表字段、deskweft_backup、完整键 deskweft.extra 和不同大小写 Deskweft 均保留。没有执行真实卸载或访问用户配置。

   - **问题**：新 tokenizer 能正确识别节边界，但删除时仅按原始文本匹配 `mcp_servers.deskweft`。TOML 允许点两侧空白和引用键，例如 `[mcp_servers."deskweft"]`、`[mcp_servers . deskweft]`、`[mcp_servers.deskweft . env]`，这些均不匹配。
   - **离线复现**：只提取并执行脚本中的 `$tokens` 到 `$text.Remove` 字符串处理片段，用 tomllib 对前后字符串解析核对；没有执行卸载脚本或访问用户配置。输入 `[mcp_servers.deskweft]\ncommand="python"\n[mcp_servers.deskweft . env]\nMODE="background"\n[ui]\ntheme="dark"\n`，输出删除了 command 所在根表，却保留 `mcp_servers.deskweft.env`。tomllib 结果仍含 `deskweft: {env: {MODE: 'background'}}`。前两种引用/空白根表则完全不被删除。
   - **最小修复**：从已确认的 header 中按 TOML 的 dotted-key 规则解析或规范化节名后再比较前三段/前两段身份；至少覆盖空白和单双引号引用键，并新增临时配置用例。不要仅为修复身份匹配而放宽到类似名称的服务。
   - **不修的后果**：用户通过合法格式化或手工增加 env 后，卸载仍留下指向该服务的注册，或留下缺少 command/url 的配置。此限制旧实现也存在；本次已重写完整节删除逻辑，可一并补齐，未发现该 tokenizer 本身破坏其他表的证据。

## 核验与边界

- 独立检查了字面花括号输入、非空替换、精确焦点、输入后读回异常、UTF-16 容量/截断、前缀误验证、根 PID/父 PID 复用、反复重显窗口、恢复读回失败保留会话、foreground 采样区间，以及未知版本不借用其他版本路线。
- 文档中的执行 unknown/queued 不重放、文本分页与结果截断、跨页稳定身份、同名项目保留、私有桌面不自动迁移 worker、授权与 rank 分离等关键契约与当前实现一致，未发现额外阻断项。
- 父任务已提供本轮全套离线回归结果：460 tests / 30.647s / OK，日志为 `.superpowers/sdd/2026-11-09-three-part-boundaries-design/final-tests.log`；本审查未重复跑全套。上述两个边界复现是独立补充证据。
- 两项修复后的限定分组结果由父任务提供：worker 35 tests / 10.444s / OK；uninstall 6 tests / 15.058s / OK。本次后续审查只读这两项修复并独立运行上述离线片段，未重复全套或开展新一轮全仓审计。

Verdict: Ship（离线范围）。两项发现均已处理，限定复核未发现阻断项；未发现新的数据破坏、授权绕过或 unknown 自动重放问题。

Not checked: 真实 GUI、已安装 HTTP 服务、真实 memory 和真实卸载均未运行；不以离线通过替代应用兼容性或现场保护证据。
