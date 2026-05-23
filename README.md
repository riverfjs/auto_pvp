# Auto PVP

PVP 计算引擎。所有战斗状态编译为整数 catalog，运行时零字符串、零字典查找、零动态分发。

## 数据管线

```
pak BinData
  + Lua Enum.lua
  → compiler_v2: Python static artifacts + handler_idx rows
  → build_db:   SQLite
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

1. **handler 注册**：`op_*` 函数写在 kernel 的 `op_*.py` 中，`gen_prefix_map` 通过 `compiler_v2` 自动发现并分配稳定索引（append-only），持久化至 `handler_registry.json`。
2. **pak/Lua 静态化**：`compiler_v2` 读取 pak BinData 与 `Data/Config/Enum.lua`，生成 `roco/generated/static/*`、`battle_globals.py`、`skill_dam_types.py`、`pak_ops.py`、`type_chart.py` 等静态 Python 产物。
3. **人工语义绑定**：少量 pak 无法机器推导的 handler 绑定留在 Python decoder / engine `op_meta`，不再放进 `rules/*.jsonl` 作为 compiler 约束层。
4. **零翻译透传**：codegen 输出元组 → SQLite → catalog_hot，所有环节使用同一二进制格式。

添加新 handler：在 `op_*.py` 写函数，运行 `uv run python -m roco.compiler_v2.gen_prefix_map`。

## 构建

```
uv run roco-refresh-artifacts                    # 静态产物 + SQLite + catalog + audits
uv run pytest tests/ -v                          # 验证
```

需要只刷新静态文件时运行：

```
uv run python -m roco.compiler_v2.gen_prefix_map
```

`pak-public-kit` 是 partial sparse submodule，只需要 `output/data` 和 `output/scripts`：

```
tools/update_pak_public_kit_sparse.sh
```

## 目录

```
roco/
├── generated/         # 全部自动生成产物 (build artifacts)
│   ├── handler_indices.py        # H_* 常量 (从 ops.py HANDLERS 派生)
│   ├── handler_order.py          # HANDLER_ORDER tuple
│   ├── handler_registry.json     # append-only handler 注册表
│   ├── prefix_handler_map.json   # buff prefix → handler 索引
│   ├── battle_globals.py         # 完整 BATTLE_GLOBAL_CONFIG 静态表
│   ├── skill_dam_types.py        # SkillDamType → Element 静态 adapter
│   ├── static/                   # pak + Lua enum 静态快照
│   ├── catalog_hot.py            # SQLite → kernel 热路径整数 catalog
│   └── catalog_debug.py          # 名字反查 catalog (facade/调试用)
├── common/            # 跨层共享: 枚举、常量、natures、bit packing
├── engine/
│   ├── common/        # Choice, RNG, kernel-local helpers
│   ├── kernel/        # 热路径: mechanics, damage, state, ops, switch, residual
│   └── facade/        # BattleEngine (名字↔ID 边界转换)
├── compiler_v2/       # 唯一 compiler 层: pak/Lua → static files / effect rows / audits
│   ├── effect_codegen/      # pak effect rows → handler_idx / audit outcome
│   ├── effect_families/     # pak family census + coverage audit
│   ├── rules/               # audit inputs/outputs, not runtime dispatch rules
│   ├── artifact.py          # SQLite → catalog_hot.py
│   └── gen_prefix_map.py    # static artifact entrypoint
└── data/
    ├── canonical.py   # pak/raw teams → in-memory canonical records
    ├── parse_pak.py   # pak canonical record builders; CLI export is debug-only
    ├── import_db.py   # record import helpers
    └── build_db.py    # 完整构建入口
```

## Reference

fixed kernel 设计参考 [pkmn/engine](https://github.com/pkmn/engine)。
