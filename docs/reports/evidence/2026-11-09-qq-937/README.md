# QQ 9.9.37 原始证据（2026-11-09）

这些 JSON 是 [路线报告](../2026-11-09-qq-9.9.37-routes.md) 的原始观测。它们来自
已删除的 `C:\Users\32677\source\winmcp` 克隆里的 `.superpowers/sdd/live2/`，
在该克隆被删前抢救出来。

**已脱敏**：账号昵称、群名、设备名替换为 `<account>`、`<group-a>`、`<device>`
等占位符（脚本见 [redact_evidence.py](../redact_evidence.py)）。所有测量数字
逐位保留，可用脚本复核：替换只改字符串标签，不碰任何数值。

未保留的部分：当轮的 97 个一次性探测脚本与 25 张截图，属于临时文件。

## 文件与用途

| 文件 | 内容 |
|---|---|
| `route-verdict.json` | 导航点击三条路线的页面与像素对照（Legacy / act.click / 真实鼠标） |
| `skill4-routes.json` | 同一目标上五种 pattern 的返回值与像素：Legacy、Invoke、SelectionItem、Toggle、act.click |
| `toggle-verdict.json` | Toggle 调用的页面与返回值 |
| `fg-compare.json` | 语义点击 vs 真实鼠标，同一窗口同一矩形；含最终树 166/67 与分组计数 |
| `ui-move-probe.json` | reveal 之后 `foreground_is_qq=false` 的对照：元素 316→316，像素 0，光标 56010 |
| `instrument-check.json` | 测量工具本身的对照：PrintWindow "size differs"，真实屏幕 1189478 |
| `d-conditions.json` | 启动条件对照 |
| `d1-scroll.json` | 两个实例上的滚动尝试（均 `not scrollable through UIA`） |
| `qq-9.9.37-adapt.json` | 首次适配探测：版本、窗口、初始树 |
| `uia-control.json` | WinForms 对照窗口 |

## 关键对照：语义点击 vs 真实鼠标

以 `route-verdict.json` 为准，同一导航按钮：

| 路线 | 返回值 | 页面 | 屏幕差异 |
|---|---|---|---|
| `LegacyIAccessible.DoDefaultAction` | `True` | messages → messages | 2464 |
| `act.click`（工具选路，报 `no visible change detected`） | `True` | messages → messages | 2075 |
| 真实鼠标点击同一矩形 | — | messages → **contacts** | 58660 |

`fg-compare.json` 里 QQ 在前台时语义点击是精确的 **0** 像素，真实鼠标 55923。

## 读这批数据时要注意的两件事

1. **页面标志是判据，不是"像素是否为 0"**。页面没变的样本仍有 2 千左右的细微
   重绘；只盯 0 会漏判，只盯"有变化"又会把 2 千当成生效。
2. **前台条件必须逐样本确认**。`ui-move-probe.json` 里 `revealed=true` 但
   `foreground_is_qq=false`，那次的前台前提没成立，不能和前台样本混谈。
