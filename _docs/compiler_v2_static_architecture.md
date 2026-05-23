# Compiler v2 static architecture

目标：把 pak 和 Lua 当作权威输入，直接导出可 import 的 Python 静态文件；JSON/JSONL 不再作为规则约束层。pak-public-kit 当前把 BinData 解包成 JSON，所以 compiler v2 仍然读取这些 JSON 文件，但它们只是 pak dump 的物理格式，不是手写规则。

## Source boundary

- `pak-public-kit/output/data/BinData/*.json`：权威表数据。技能、效果、buff、全局战斗常量都从这里读。
- `pak-public-kit/output/scripts/lua/Data/Config/Enum.lua`：权威枚举名。`EffectType`、`BuffType`、`SkillDamType`、`WeatherType` 等用于给 pak 数字轴命名。
- `pak-public-kit/output/scripts/lua/Common` 与 `NewRoco/Modules/Core/Battle`：可扫描 enum 引用，作为审计信号，不作为运行时规则。

`Data/tinyio_Config/*.lua` 不是权威表数据，它只是 TinyData 访问器。不要从这些文件反推数据。

## Compiler shape

```
PakSource(BinData)
LuaEnumSource(Enum.lua + battle lua refs)
  -> StaticBundle
  -> emit .py modules
```

正式实现位于 `roco/compiler_v2`，静态 pak/Lua 快照输出到 `roco/generated/static`：

```bash
uv run python -m roco.compiler_v2.gen_prefix_map
```

其中 `roco/generated/static` 会生成：

- `lua_enums.py`：Lua enum 的静态 dict，以及核心战斗 Lua 对这些 enum 的引用计数。
- `pak_axes.py`：pak 数字轴 join Lua enum 后的静态表，例如 `EFFECT_ORDER_NAMES`、`BUFFBASE_ORDER_NAMES`、`BUFF_BASE_TO_ORDER`、`BATTLE_GLOBAL_*`、`SKILL_DAM_TYPE_TO_ELEMENT`。
- `manifest.py`：输入源 hash，后续用于 drift check。

根级 `roco/generated` 还会生成 runtime/data 直接消费的静态文件：

- `battle_globals.py`：完整 `BATTLE_GLOBAL_CONFIG`，不再通过手写白名单挑选。
- `skill_dam_types.py`：由 `Enum.SkillDamType + TYPE_DICTIONARY` 生成的 pak damage type → kernel element adapter。

## Design rules

- JSON/JSONL 只能是 pak dump 的输入格式或审计输出格式，不能承载“哪个效果应该走哪个 handler”的语义规则。
- pak schema 自带的轴优先：`EFFECT_CONF.effect_order`、`BUFFBASE_CONF.buffbase_order`、`BUFF_CONF.buff_base_ids`。
- Lua enum 只给数字轴命名和校验，不执行 Lua，不从访问器脚本抽数据。
- 人工语义绑定应进 Python 代码，例如 handler decorator 或 decoder 函数，和测试一起变更；不要再拆到手写 JSONL。
- 静态输出必须是纯 Python 常量，运行时 import 后不读 pak、不读 Lua、不读 JSON。
