# Auto PVP

当前项目是洛克王国精灵 PVP 的计算引擎。战斗管道参考 `/Users/River/Documents/Code/engine` 的显式阶段、two-tier data model 和 packed bitfields：`BattleEngine` 是 fixed kernel 的薄 facade，真正热路径由 `update(state, c1, c2, options)` 推进，天气、印记、奉献、技能后效和特性状态都编译成整数 catalog 与固定 op/stage 流执行。

数据和技能/特性/天气联动以 `/Users/River/Documents/Code/NRC_AI` 的洛克王国数据口径为准。这里没有岩系，也不把钢作为属性；结构化属性字段只接受洛克王国规范属性，`地面系` 归一到 `地`，正式机械属性使用 `机械`。

核心边界：

- `roco/engine/kernel.py`、`kernel_state.py`、`kernel_effects.py`、`kernel_catalog.py`: 热路径，只使用整数 ID、tuple index、packed state 和固定函数表。
- `roco/engine/catalog_hot.py`: 战斗用热 catalog，全整数 tuple；`catalog_debug.py` 只用于展示和名字反查。
- `roco/engine/battle.py`: 外层 facade，负责持有 `KernelState` 和调用 fixed kernel，不包含事件总线或动态系统注册。
- `roco/data`: `raw/canonical JSONL -> SQLite -> hot/debug artifact` 的数据管线。
- `_data` / `_db`: 生成数据产物。
