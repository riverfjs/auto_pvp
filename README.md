# Auto PVP

PVP 计算引擎。所有战斗状态编译为整数 catalog，运行时零字符串、零字典查找、零动态分发。

## 数据管线

```
pak BinData
  → parse_pak:  canonical JSONL  (effect_rows = codegen 输出的 handler_idx 元组)
  → import_db:  SQLite
  → artifact:   catalog_hot.py   (纯整数元组，kernel 唯一数据源)
  → kernel:     HANDLERS[handler_idx](ctx, row)
```

全链路同一元组格式 `(handler_idx, timing, target, rate, p0-p3)`，无中间翻译层。

## Kernel

入口 `mechanics.update(state, c1, c2) → KernelResult`。`KernelState` 是不可变 NamedTuple，每回合产出新状态。

热路径阶段：priority → execute → damage → after_move → end_turn → check_winner。效果通过 `run_skill_timing` 按 timing 筛选 effect_rows，索引 HANDLERS 数组分发到 op 函数。

handler 按职责分文件：

- `op_mods` — 伤害、增益、削弱、修饰
- `op_resources` — 能量、生命
- `op_marks` — 印记
- `op_status` — 状态异常
- `op_cute` — 萌化

## 效果编译

效果分类完全基于数字结构，不匹配中文文本。

1. **handler 注册**：`op_*` 函数写在 kernel 的 `op_*.py` 中，`gen_prefix_map` 自动发现并分配稳定索引（append-only），持久化至 `handler_registry.json`。`ops.py` 从注册表动态构建 HANDLERS 数组，无手工列表。
2. **buff 分类**：`effect_codegen` 按精确 `buff_base_id` 或前缀族（`buff_base_id // 1000`）映射到 handler 索引。映射表由 `gen_prefix_map` 扫描 BUFF_CONF 自动生成。
3. **零翻译透传**：codegen 输出元组 → JSONL → SQLite → catalog_hot，所有环节使用同一二进制格式。

添加新 handler：在 `op_*.py` 写函数，运行 `uv run python -m roco.compiler.gen_prefix_map`。

## 构建

```
uv run python -m roco.compiler.gen_prefix_map   # handler 注册 + prefix 映射
uv run python -m roco.data.parse_pak             # pak → JSONL
uv run python -m roco.data.build_db              # JSONL → SQLite → catalog
uv run pytest tests/ -v                          # 验证
```

## 目录

```
roco/
├── engine/
│   ├── common/       # Choice, RNG, packed bitfields, rules
│   ├── kernel/       # 热路径: mechanics, damage, state, ops, switch, residual
│   ├── generated/    # catalog_hot.py, catalog_debug.py (编译产物)
│   └── facade/       # BattleEngine (名字↔ID 边界转换)
├── compiler/
│   ├── effect_codegen.py   # pak → handler_idx 分类
│   ├── artifact.py         # SQLite → catalog_hot.py
│   ├── gen_prefix_map.py   # handler 自动发现 + prefix 映射生成
│   └── generated/          # handler_indices.py, handler_registry.json, prefix_handler_map.json
├── data/
│   ├── parse_pak.py   # pak BinData → canonical JSONL
│   ├── import_db.py   # JSONL → SQLite
│   └── build_db.py    # 完整构建入口
└── common/            # 跨层共享枚举
```

## Reference

fixed kernel 设计参考 [pkmn/engine](https://github.com/pkmn/engine)。
