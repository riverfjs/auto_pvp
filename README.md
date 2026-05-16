# Auto PVP

当前项目是洛克王国精灵 PVP 的计算引擎。战斗管道参考 `/Users/River/Documents/Code/engine` 的显式阶段、two-tier data model 和 packed bitfields：`BattleEngine` 只推进回合、切换、出招与事件派发，天气、印记、奉献、技能后效、特性联动挂在 `EventBus` 的 hook 上。

数据和技能/特性/天气联动以 `/Users/River/Documents/Code/NRC_AI` 的洛克王国数据口径为准。这里没有岩系，也不把钢作为属性；结构化属性字段只接受洛克王国规范属性，`地面系` 归一到 `地`，正式机械属性使用 `机械`。

核心边界：

- `roco/engine`: 回合推进、状态模型、伤害和属性克制计算。
- `roco/systems`: 技能效果、天气、印记、奉献等事件处理器。
- `roco/data`: 从原始 Wiki/结构化数据解析到规范化 SQLite，再编译为运行时 catalog。
- `_data` / `_db`: 生成数据产物。
