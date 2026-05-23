# Static data audit design

目标：把战斗数据真源收回到 pak/Lua/generated，engine 只写战斗执行逻辑；compiler 只允许写结构推导和少量明确 policy，不能长期保存 pak id -> handler 的人工表。

## Boundary model

| Layer | Allowed source | Allowed content | Forbidden content |
| --- | --- | --- | --- |
| `pak-public-kit/output/data/BinData` | pak dump | 原始表事实 | 手写规则 |
| `pak-public-kit/output/scripts/lua/Data/Config/Enum.lua` | Lua enum | pak 数字轴命名 | 从访问器脚本反推表数据 |
| `roco/generated/*` | compiler output | importable static facts | 运行时读取 pak/Lua/JSON |
| `roco/compiler_v2/*` | compiler code | source readers, emitters, structural decoders | 长期 `id/order -> handler` 人工映射 |
| `roco/engine/*` | generated + common enums | concrete battle logic | pak id、effect id、buff order、JSONL rule |
| `roco/common/*` | project enum/policy | typed adapters, bit layout, stable domain defaults | pak 派生大表 |

## Classification

- `generated_fact`: pak 或 Lua 中直接存在的信息，必须生成。例如 `BUFFBASE_ORDER`、`TYPE_CHART_BPS`、`BATTLE_GLOBAL_CONFIG`。
- `derived_fact`: 多个 pak/Lua 表 join 后得到的信息，也必须生成。例如 counter response skill table、mark cover groups。
- `structural_decoder`: compiler 中的算法，用 pak 轴和参数形状推出 handler。它可以写逻辑，但不能列完整 id 表。
- `enum_adapter`: 项目 enum 与 pak enum 的小型桥接。允许临时存在，但需要有 drift check 或生成替代计划。
- `kernel_policy`: pak/Lua 不表达的运行时决策。允许存在，但必须小、命名清楚、测试覆盖。
- `semantic_debt`: 任何人工 `effect_id`、`buffbase_order`、`base_id`、`prefix` 到 handler/flag 的表。它可以短期保留，但不能当最终架构。
- `legacy_shadow`: 旧 compiler/rules 中仍能影响测试或读者判断的重复规则源。迁移时必须删或标成非权威。

## Current audit result

当前 engine 主要从 generated 读取战斗数据：

- `catalog_hot`
- `handler_table`
- `handler_indices`
- `counter_skill_table`
- `buff_immunity_table`
- `mark_groups`
- `battle_globals`
- `skill_dam_types`
- `natures`
- `canonical_adapters`

engine 里没有发现大规模 pak id -> handler 的手写战斗表。剩余风险集中在 compiler/data/common：

| Location | Class | Problem | Target |
| --- | --- | --- | --- |
| engine `op_meta` handler axes | resolved metadata | `buffbase_order/prefix/base_id` 覆盖声明已从 compiler 表迁到 engine handler；`handles_buff` 使用 `Enum.BuffType`，多数 exact anchors 使用 `BUFFBASE_CONF.editor_name` 再由 compiler 解析 | 剩余 2 个 `handles_base_id` 是 duplicate-name mark rows，继续结构化或移到 generated adapter |
| exact runtime effect coverage | structural_decoder/generated | `EXACT_EFFECT_RULES` 已删除；heal/吸血/能量/连击/冷却/迅捷/交换/净化/标记驱散/复制增益已走 `effect_order/type/param shape` 或 generated weather | 新复合语义优先扩展 family decoder，不恢复 id 表 |
| `roco/generated/skill_dam_types.py` | `generated_fact` | 已生成 `SkillDamType -> Element`，替换了 compiler/data 两份映射 | 后续只做 drift check |
| `roco/generated/battle_globals.py` | `generated_fact` | 已生成完整 `BATTLE_GLOBAL_CONFIG`，删除了 `PAK_RULE_KEYS` 白名单 | 消费者只读需要的 key |
| weather generation | enum_adapter/policy | 已删除 `compiler_v2/semantics.py`；weather 生成从 Lua `Enum.WeatherType` 符号名折叠到 kernel enum，默认回合数是函数策略 | 继续用 generated/weather decoder drift tests 锁住 |
| ability flag derivation | derived_fact | 已从手写 effect_id 表改为 `EFFECT_CONF.editor_name + effect_param` 结构推导 | 后续只扩展 family/keyword，不回退到 id 表 |
| buff immunity derivation | derived_fact | 已从手写 buff_id 表改为 `BUFF_CONF.desc` 中“免疫…”短语推导 | 后续补充 keyword/alias，并保持 drift tests |
| `roco/data/parse_pak.py` skill element lookup | generated consumer | 已改读 `roco.generated.skill_dam_types.SKILL_DAM_TYPE_TO_ELEMENT_NAME` | 后续保持 consumer，不再维护本地表 |
| `roco/common/natures.py` | generated consumer | `NATURE_MOD`/`IV_STAT_MAP` 已改读 `roco.generated.natures`；生成源是 `NATURE_CONF.positive_effect/negative_effect` + `ATTRIBUTE_CONF`，比例读 `positive_effect_proportion/negative_effect_proportion` | pak 更新后重跑 compiler 即更新 |
| `roco/data/parse_pak.py` skill category lookup | generated consumer | `MOVE_CATEGORY_TO_CN` 已改读 `roco.generated.canonical_adapters`；生成源是 `moves.json` 与 `SKILL_CONF` 的 join | 后续保持 consumer，不再维护本地表 |
| `roco/data/parse_pak.py` mark definitions | generated consumer | 旧 `MARK_DEFS` 已移到 `roco.generated.canonical_adapters.CANONICAL_MARK_DEFS`；生成源是 `DESC_NOTE_CONF` 与 common `MarkIdx` bit layout | 后续若 pak 增加新印记，扩展 compiler adapter 并重跑生成 |

## Design rules

1. engine 不允许新增 pak id、effect id、buff id、buffbase order、prefix 的手写映射。
2. compiler 输出文件 header 必须说明来源：`pak/Lua`、`derived`、`policy`、或 `semantic debt`。
3. `semantic_debt` 不能静默增长。新增项必须同时增加审计输出中的 debt count，并解释为什么不能结构化推导。
4. 旧 `roco/compiler_v2/rules/*.jsonl` 不能再作为 handler dispatch 权威入口。测试若仍引用旧路径，只能用于迁移对照。
5. pak 更新后的第一道门禁不是“测试刚好过”，而是审计报告中：
   - generated fact drift 可解释；
   - semantic debt 未增加，或增加项有明确 issue；
   - engine handwritten data count 不增加。

## Migration order

1. 继续审计 engine `handles_base_id` 剩余 2 个 duplicate-name mark 例外，能结构化的移到 decoder/generated adapter。
2. 对 immunity/ability flag 的派生规则补充更多 pak 证据和 alias；不再恢复 id 表。
3. 清理旧 codegen/rules 测试引用，避免旧规则源继续误导。

## Temporary audit prototype

临时原型位于 `_experiments/data_audit/`，只读 Python AST，不 import 生产模块：

```bash
.venv/bin/python _experiments/data_audit/audit_static_data.py
```

它会输出：

- `_experiments/data_audit/current_static_data_audit.md`
- `_experiments/data_audit/current_static_data_audit.json`

这个原型不是最终 compiler 功能，只用于设计阶段反复验证“哪里还有手写数据事实”。
