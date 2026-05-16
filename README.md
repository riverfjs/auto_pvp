# Auto PVP

当前项目的战斗管道采用 Pokemon-engine 风格的显式阶段模型：`BattleEngine` 只推进回合、切换、出招与事件派发，具体天气、印记、奉献、技能后效等都挂在 `EventBus` 的 hook 上。

数据和技能联动以 `NRC_AI` 的洛克王国数据口径为准：属性、技能、印记、性格与数值计算都应落到本项目 `roco/data`、`roco/engine`、`roco/systems` 的洛克语义里。这里没有宝可梦的岩系；洛克王国的相关地表/岩土语义统一归入 `地` 系，兼容输入里的 `地面`，旧输入 `岩` 只作为别名归一到 `地`。

核心边界：

- `roco/engine`: 回合推进、状态模型、伤害和属性克制计算。
- `roco/systems`: 技能效果、天气、印记、奉献等事件处理器。
- `roco/data`: 从原始 Wiki/结构化数据解析到本地 JSON/SQLite。
- `_data` / `_db`: 生成数据产物。
