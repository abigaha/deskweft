# 2026-11-09 三个 agent 部署

用户授权部署到三个 agent 后 push。部署依据为
[三部分职责实现](2026-11-09-three-part-boundaries-implementation.md)，目标根据已有配置及
历史同步脚本确定为 Codex、Claude、DSH，不改其他客户端。

## 部署与回退

- 三个 skill 目录：`%USERPROFILE%/.codex/skills/windows-app-automation`、
  `%USERPROFILE%/.claude/skills/windows-app-automation`、
  `%USERPROFILE%/.dsh/skills/windows-app-automation`。
- 每个目录同步 6 个分发资源，新增工具参考与案例，排除 `__pycache__` / pyc。
  独立检查文件集合与 SHA256 均与仓库一致。
- 同步 `%LOCALAPPDATA%/deskweft` 下的 skill 和辅助安装文件；Python 包继续使用 editable
  安装，指向本仓库，没有再放会遮蔽安装的 `deskweft/` 代码副本，也未新增依赖。
- 三个客户端原有 MCP 地址均为 `http://127.0.0.1:8765/mcp`，无需修改配置。
  部署前后配置及实际 memory 文件哈希保持不变。
- 部署前备份在本机
  `.superpowers/sdd/2026-11-09-three-part-boundaries-design/deployment-20261109-180423/`。
  备份不上传；恢复时使用备份中对应客户端及 runtime-files 内容，再重启自己的服务。
- 经命令行、创建时间和计划任务归属核验后，仅重启 DeskWeft helper 及其原 worker。
  服务 PID 从 25824 变为 9524，仍只监听 `127.0.0.1:8765`。

## 当轮验证

- 提交前完整离线测试：461 项，33.662 秒，全部通过。仍有既有 socket ResourceWarning。
- 已安装 HTTP 服务：18 个工具的名称、description、输入 schema 与当前源码逐项相同。
- `windows()` 返回窗口元数据结构有效；不记录用户窗口标题或内容。
- 连续三次 `see(hwnd=0)` 在 provider 前拒绝，`execution_state=not_started`，复用同一个
  worker，未产生逐次新增进程。
- `private_desktop(action="status")` 只读状态可用；未 create/show/hide/switch。
- 不存在应用的 `@unversioned` recall 返回零匹配；memory 未被写入或迁移。
- [HTTP 验证摘要](evidence/2026-11-09-boundaries/deployed-http.json)与
  [三客户端资源哈希](evidence/2026-11-09-boundaries/deployed-skills.json)保存当轮证据。

客户端磁盘部署完成；没有重启 Codex、Claude、DSH 的现有会话。新会话可重新读取技能和
服务工具清单；已打开会话可能保留旧元数据，需要客户端重新连接或重载。此次健康检查
不代替真实 GUI 自检、QQ/微信动作或完整名单验收，也没有为了验证而重放任何业务操作。
