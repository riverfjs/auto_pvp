# Auto PVP

当前项目是洛克王国精灵 PVP 的计算引擎。战斗管道参考 `/Users/River/Documents/Code/engine` 的显式阶段、two-tier data model 和 packed bitfields：`BattleEngine` 是 fixed kernel 的薄 facade，真正热路径由 `update(state, c1, c2, options)` 推进，天气、印记、奉献、技能后效和特性状态都编译成整数 catalog 与固定 op/stage 流执行。

数据和技能/特性/天气联动以 `/Users/River/Documents/Code/NRC_AI` 的洛克王国数据口径为准。这里没有岩系，也不把钢作为属性；结构化属性字段只接受洛克王国规范属性，`地面系` 归一到 `地`，正式机械属性使用 `机械`。

核心边界：

- `roco/engine/common`: 跨 kernel 的 `Choice`、side/result id、RNG 和 packed bit helpers。
- `roco/engine/kernel`: 热路径包，入口是 `mechanics.update()`；状态、伤害、残余结算、切换生命周期和 op table 分文件放置。`__init__.py` 不做便利 re-export。
- `roco/engine/generated`: 编译生成的 `catalog_hot.py` / `catalog_debug.py`；kernel 只读 hot catalog，debug/facade 才读名字反查。
- `roco/engine/facade`: 外层 `BattleEngine`，负责名字到整数 ID 的边界转换和持有 `KernelState`。
- `roco/compiler`: 技能/特性效果分类、effect row 编译、artifact 生成；不进入 battle kernel。
- `roco/data`: `raw/canonical JSONL -> SQLite` 的数据仓库管线，随后由 compiler 生成 hot/debug artifact。
- `_data` / `_db`: 生成数据产物。
