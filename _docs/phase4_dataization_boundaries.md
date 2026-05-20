# Phase 4 数据化边界

Phase 4 评估过的"是否把某个 Python 常量 / dict 迁到 JSONL 规则文件"
全部决策清单。**核心原则**：pak → `roco/generated/` 静态产物，
runtime 只读 generated；避免任何手写 dict 隐式扮演规则真源。

迁移有现成模板（`roco/compiler/effect_codegen/buff_immunity_decoders.py`
+ `roco/compiler/codegen/buff_immunity_codegen.py`），但模板不是把
所有 Python 常量当成"应该迁"。下面每条都用同一组准则评估：

* 数据是不是真正的"规则映射"（curated by humans，无 enum 双绑定）？
* 体积是不是足够大，使得 schema 校验 + drift 测试值得？
* 多个消费者吗？JSONL 化能不能消除重复源？

凡是任一答案为否的，就不迁。

## 评估后不数据化

### Weather pak-code → kernel-enum 映射

* 现位置：`roco/compiler/codegen/weather.py` 顶部的
  `_PAK_WEATHER_TO_KERNEL`。
* 体积：4 条（NONE / RAIN / SNOW / SANDSTORM）。
* 不迁原因：**pak schema adapter** — pak weather id → project
  `WeatherType` enum。enum 与映射双向绑定；JSONL 化只会让任何 enum
  改名要改两处。这是 4 条非常稳定的 schema 翻译，体量不够。
* 重新考虑触发：pak 新增 5+ 天气类型；或 `WeatherType` enum 不再
  是单一定义点。

### Weather default turns

* 现位置：`roco/compiler/codegen/weather.py` 顶部的
  `_WEATHER_DEFAULT_TURNS`。
* 体积：4 条。
* 不迁原因：**kernel policy + test-backed behavior** — 这些数值
  描述"天气默认持续多少回合"，由 kernel 行为决定（首个回合结束的
  tick 扣 1，因此 `8` 对应 canonical 的"还剩 7 回合"基线），并被
  既有 kernel 测试断言锁住。与上一条 schema 映射不同：这是 *policy*。
  JSONL 化会把 policy 决策从代码 + 测试拆到第三处。
* 重新考虑触发：开始支持多种 default turns 曲线（PvE vs PvP 差异
  化）；或 policy 来源从代码挪到运营配置。

### Skill damage type → element

* 现位置：`roco/compiler/codegen/counter_skills.py` 顶部的
  `_PAK_SKILL_DAM_TYPE_TO_ELEMENT`。
* 体积：19 条。
* 不迁原因：pak schema adapter — pak `skill_dam_type` → project
  `Element` enum value。和上面 weather pak-code 一样的理由：与
  `Element` enum 双绑定。
* 重新考虑触发：pak schema 改版（damage type 字段重新编号）需要
  对照表。

### Bloodline magic seed

* 现位置：`roco/data/migrate.py` 行 334-338。
* 体积：2 条（`willpower_strike`, `leader_transform`）。
* 不迁原因：DB schema reference seed，不是 pak effect rule；体积
  极小。
* 重新考虑触发：bloodline magic 扩到 5+ 条固定条目。

### Elements / weathers DB-init seed

* 现位置：`roco/data/migrate.py` 行 291-310。
* 体积：18 条 elements + 4 条 weathers。
* 不迁原因：与 Python `ELEMENT_CODES` / `WeatherType` enum 双向
  绑定；JSONL 化会断 import 链（enum 是 type-checked 入口，JSONL
  无法承担类型角色）。
* 重新考虑触发：迁移到外部 DB schema 工具（Alembic 等），seed
  不再由 Python 代码生成。

### `_MARK_TAG_MAP`

* 现位置：`roco/data/import_db.py` 行 116-130。
* 体积：13 条。
* 不迁原因：详见
  [phase4_mark_tag_map_audit.md](./phase4_mark_tag_map_audit.md) ——
  该 dict 语义本身就有错位嫌疑（mark code → pak prefix vs 消费处
  比的是 handler index），固化成 JSONL 等于把可能错误的规则固化
  成规则源。Phase 4 选项是"保留 + 写 doc + 加注释指向 doc"。
* 重新考虑触发：见 mark audit doc 的"重新审视触发"小节。

### `MARK_COVER_GROUPS` (mark groups)

* 现位置：`roco/generated/mark_groups.py`（pak 自动生成；驱动模块
  `roco/compiler/codegen/marks.py`）。
* 不迁原因：已经是 generated 产物（pak `BUFF_CONF.buff_groupsigns`
  派生），无需"数据化"。
* 重新考虑触发：N/A。

### `MARK_DEFS` in parse_pak.py

* 现位置：`roco/data/parse_pak.py` 顶部（~行 70+）。
* 体积：~12 条 desc_id → mark code 元数据。
* 不迁原因：MarkIdx enum adapter — 与 Python `MarkIdx` enum 双绑定。
  与 `_MARK_TAG_MAP` 不同，本表**真的**驱动 marks canonical 入口，
  并不 inert；但其语义同样属于 enum adapter，不是规则。
* 重新考虑触发：MarkIdx enum 不再是唯一定义点；或 pak 改写
  desc_id 命名空间。

## 总结

Phase 4 不新建任何 `roco/compiler/rules/*.jsonl`。已有的 rules
（`exact_effects.jsonl` / `prefix_handlers.jsonl` / `buff_immunity.jsonl`
/ `effect_gap_acknowledgements.jsonl` / `effect_families.jsonl`）
保持现状。

下一轮真要迁某条规则时，按
`roco/compiler/effect_codegen/buff_immunity_decoders.py` +
`roco/compiler/codegen/buff_immunity_codegen.py` 这一对模板做即可：
loader 严格 schema + import-time self-check + codegen render/write
分层 + tests 三层（accept / reject / drift）。
