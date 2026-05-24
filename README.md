# Auto PVP

PVP 固定内核模拟器。运行时战斗代码只导入整数化的静态目录；不读取
pak 文件、Lua、JSON、JSONL、SQLite，也不依赖动态规则注册表。

## 更新路径

pak dump 更新后按这个顺序执行：

```bash
tools/update_pak_public_kit_sparse.sh
uv run roco-refresh-artifacts
uv run pytest -q
```

`pak-public-kit` 是 sparse partial submodule。更新脚本只拉取：

```text
pak-public-kit/output/data
pak-public-kit/output/scripts
```

`output/assets` 故意不 checkout。

## 数据流

```text
pak-public-kit/output/data
+ pak-public-kit/output/scripts/lua/Data/Config/Enum.lua
    |
    v
compiler_v2
    - 静态 pak/Lua 事实
    - 结构化 effect 解码器
    - 从 pak 派生的 primitive rows
    |
    v
roco/generated/primitive_map.json
roco/generated/static/*
    |
    v
engine 运行时生成物构建器
    - primitive key -> handler 绑定
    - handler 分发表
    |
    v
roco/generated/*
    |
    v
roco.data.catalog_compiler
    - pak canonical 记录
    - 已链接的技能/特性 runtime rows
    |
    v
roco/generated/catalog_hot.py
roco/generated/catalog_debug.py
    |
    v
engine/kernel
    - hot.PETS / hot.SKILLS
    - hot.SKILL_EFFECT_ROWS / RANGES
    - HANDLERS[handler_idx](ctx, row)
```

effect runtime row 的布局固定：

```text
(handler_idx, timing, target, flags, cond, p0, p1, p2, p3)
```

旧文档有时把它写成 `(handler_idx, timing, target, rate, p0-p3)`；实际运行时
tuple 是上面的 9 字段。

compiler row 不是 runtime row。compiler 侧使用：

```text
(primitive_key, timing_key, target, rate, p0, p1, p2, p3)
```

pak 有命名来源时，`primitive_key` 必须来自 pak：
`effect_order:ET_*`、`buff_type:BFT_*`、
`mark_note:<DESC_NOTE_CONF.note>`、`status_note:<DESC_NOTE_CONF.note>`、
或 `effect_kind:<EFFECT_CONF.type>`。只有 pak 没有直接表达的解释，才使用
项目显式 namespace，例如 `struct:*` 或 `source_context:*`。

`timing_key` 对应 pak `cast_moment` 时，格式是
`battle_event:<Enum.BattleEvent symbol>`。engine-only 阶段必须使用显式的
`engine_hook:*` key，并且只在 engine linker 里绑定。

## 刷新流水线

`uv run roco-refresh-artifacts` 按顺序执行这些步骤：

1. `roco.compiler_v2.gen_prefix_map`
   在 `roco/generated/` 下生成静态 pak/Lua 事实、BattleEvent 常量和 primitive maps。
2. `roco.engine.kernel.gen_runtime_artifacts`
   生成 engine-owned 的 `handler_indices.py`、`handler_order.py` 和
   `handler_table.py`。
3. `roco.data.catalog_compiler`
   从 pak 派生的 canonical 记录构建 `catalog_hot.py` 和 `catalog_debug.py`，
   并通过 engine 契约链接 primitive rows。
4. `roco.compiler_v2.build_effect_families`
   写入生成的审核输出：
   `roco/generated/audit/effect_families.jsonl` 和
   `_docs/effect_family_audit.md`。
5. `roco.compiler_v2.build_effect_families --check`
   校验审核输出是确定性的。
6. `roco.compiler_v2.pak_schema_audit`
   写入 `_docs/pak_schema_audit.md`。
7. `roco.compiler_v2.pak_schema_audit --check`
   校验 schema audit 是确定性的。
8. `roco.compiler_v2.bindata_coverage_audit`
   写入 `roco/generated/audit/bindata_coverage.json`。
9. `roco.compiler_v2.bindata_coverage_audit --check`
   校验 bindata coverage audit 是确定性的。

`uv run roco-refresh-artifacts --check` 用于 clean-tree/CI 校验。真实 pak 更新后
不要立刻用 `--check` 当作刷新命令；真实更新预期会产生 diff。

## 生成物

运行时和数据生成文件放在 `roco/generated/`：

```text
catalog_hot.py              kernel 运行时目录
catalog_debug.py            名称和调试查询表
battle_events.py            Enum.BattleEvent 运行时常量
handler_table.py            handler_idx -> op_* 函数表
handler_indices.py          H_* 常量
handler_order.py            engine handler 顺序
primitive_map.json          BUFF_CONF / BUFFBASE_CONF -> primitive key 映射
buffbase_params.py          BUFFBASE_CONF 参数
pak_ops.py                  pak op/prefix 元数据
battle_globals.py           BATTLE_GLOBAL_CONFIG 常量
skill_dam_types.py          SkillDamType -> 属性适配器
type_chart.py               pak 属性克制表
weather_decoders.py         生成的天气 effect 解码器
counter_skill_table.py      反击响应技能查询表
buff_immunity_table.py      从 pak 文本/结构派生的免疫标记
mark_groups.py              mark 覆盖分组
natures.py                  性格属性修正
canonical_adapters.py       pak -> canonical 适配器
static/lua_enums.py         Lua enum 快照
static/pak_axes.py          effect/buff 轴与 enum 名称的生成快照
static/manifest.py          源文件哈希
audit/effect_families.jsonl 生成的机器可读审核数据
```

generated 顶层模块是运行时和数据适配器。`static/pak_axes.py` 用于检查 pak
轴数据，故意不重复 `battle_globals.py` 或 `skill_dam_types.py`。

`roco/generated/audit/effect_families.jsonl` 不是规则文件，而是生成出来的审核数据。
不要手动编辑。

## Pak 查询 CLI

`uv run roco-pak` 是 pak 数据的检查入口。它直接读取
`pak-public-kit/output/data`，不导入 engine，也不导入 generated 运行时目录。

```bash
uv run roco-pak pet 音速犬
uv run roco-pak skill 火焰箭
uv run roco-pak skill 毒沼
uv run roco-pak ability 专注力
```

CLI 支持：

- pet name/id -> 基础技能、血脉技能、技能石技能、特性
- skill name/id -> 能学习该技能的精灵，包括技能石解锁来源
- ability name/id -> 拥有该特性的精灵

技能石解锁文本来自 pak 表 join：
`LEVEL_SKILL_CONF`、`BAG_ITEM_CONF`、`handbook-rewards.json` 和
`PET_HANDBOOK`。

## Engine 运行时

热路径在 `roco/engine/kernel`。

`mechanics.update(state, c1, c2)` 执行：

```text
start_turn -> order -> execute -> damage -> after_move -> end_turn -> check_winner
```

engine 导入：

```python
from roco.generated import catalog_hot as hot
from roco.generated.handler_table import HANDLERS
```

运行时流程：

```text
skill_id
  -> hot.SKILL_EFFECT_RANGES[skill_id]
  -> hot.SKILL_EFFECT_ROWS[start:end]
  -> run_skill_timing(...)
  -> HANDLERS[handler_idx](ctx, row)
```

engine 文件只写具体战斗逻辑。不维护 pak id、effect id、buff id、
buffbase order、prefix 或 JSONL 分发表。

## Compiler 规则

compiler v2 优先使用 pak 结构：

```text
EFFECT_CONF.effect_order
BUFFBASE_CONF.buffbase_order
BUFF_CONF.buff_base_ids
SKILL_CONF.skill_result
Lua Enum 数字轴名称
```

compiler 允许做：

- source 读取器和生成器
- 基于 pak axes 与参数形状的结构化解码器
- pak 不编码运行时行为时的小型显式策略适配器
- 从 pak/Lua 结构派生的 primitive keys 和 primitive params

长期禁止模式：

- 手写维护 `effect_id -> handler`
- 手写维护 `buff_id -> handler`
- 手写维护 `buffbase_order -> handler`
- compiler import `roco.engine`
- JSONL 文件充当运行时分发规则
- engine import pak/Lua/JSON/SQLite

compiler 不能维护 engine op registry。engine 绑定放在
`roco/engine/artifacts/primitive_bindings.py`，以及相关 `op_*` 函数旁边的
`op_meta` 声明。

## 目录结构

```text
pak-public-kit/              sparse submodule，只包含 output/data + output/scripts
tools/                       维护脚本，包括 sparse pak 更新
roco/generated/              生成的运行时/数据产物
roco/generated/audit/        生成的机器可读审核数据
roco/compiler_v2/            pak/Lua 读取器、生成器、结构化解码器
roco/compiler_v2/static_artifacts/
                             按领域拆分的静态产物生成器
roco/compiler_v2/rules/      仅保留手写迁移输入，不作为 dispatch 来源
roco/data/                   pak/team 规范化和刷新编排
roco/pak_query/              独立 pak 查询 CLI
roco/engine/kernel/          固定整数战斗内核
roco/engine/facade/          面向用户的 name/id 边界
_docs/effect_family_audit.md 生成的人类可读 effect 覆盖审核
_docs/pak_schema_audit.md    生成的 pak schema/axis 审核
_docs/damage-formula.md      手写伤害公式说明
```

## 开发命令

```bash
uv run roco-refresh-artifacts
uv run pytest -q
```

只重新生成静态 pak/Lua 层：

```bash
uv run python -m roco.compiler_v2.gen_prefix_map
```

新增 runtime handler：

1. 在 `roco/engine/kernel` 下写一个 `op_*` 函数。
2. 只有 handler 拥有 pak axis 时才添加 `op_meta` 声明；对
   `effect_order:*`、`struct:*` 或 `source_context:*` keys，在
   `primitive_bindings.py` 里加绑定。
3. 运行 `uv run roco-refresh-artifacts`。
4. 添加或更新聚焦测试。

## 参考

固定内核形态参考了 [pkmn/engine](https://github.com/pkmn/engine)。
