# 温室灌溉用量预测功能与验证

领域为 AI/ML / 传统ML。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 阀门遥测 | 按阀门及测点窗口汇总可核验的补水流量 | 运行证据第 1 段 | `src/greenhouse/valve_telemetry/contracts.py` `src/greenhouse/valve_telemetry/analysis.py` `src/greenhouse/valve_telemetry/service.py` | `tests/test_valve_telemetry.py` |
| M2 根区水分 | 隔离未来观测和非目标深度 | 运行证据第 2 段 | `src/greenhouse/rootzone_history/contracts.py` `src/greenhouse/rootzone_history/analysis.py` `src/greenhouse/rootzone_history/service.py` | `tests/test_rootzone_history.py` |
| M3 蒸腾回归 | 用时间隔离数据训练岭回归并与历史水量对照 | 运行证据第 3 段 | `src/greenhouse/evapotranspiration/contracts.py` `src/greenhouse/evapotranspiration/analysis.py` `src/greenhouse/evapotranspiration/service.py` | `tests/test_evapotranspiration.py` |
| M4 偏差检验 | 记录残差区间，联锁缺测和工况漂移 | 运行证据第 4 段 | `src/greenhouse/moisture_band/contracts.py` `src/greenhouse/moisture_band/analysis.py` `src/greenhouse/moisture_band/service.py` | `tests/test_moisture_band.py` |
| M5 分区拨水 | 联合班次水源、泵组和阀门开启窗口做分配 | 运行证据第 5 段 | `src/greenhouse/irrigation_quota/contracts.py` `src/greenhouse/irrigation_quota/analysis.py` `src/greenhouse/irrigation_quota/service.py` | `tests/test_irrigation_quota.py` |
| M6 农事账目 | 以计量单和分区授权核对超额领用 | 运行证据第 6 段 | `src/greenhouse/watering_ledger/contracts.py` `src/greenhouse/watering_ledger/analysis.py` `src/greenhouse/watering_ledger/service.py` | `tests/test_watering_ledger.py` |

## 陷阱登记

| TRAP | 输入情形 | 错误风险 | 处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-23 | 连续班次边界上有阀门采样 | 重复读取相同的采样点 | 班次使用半开区间 | `src/greenhouse/valve_telemetry/analysis.py` | `tests/test_valve_telemetry.py::test_adjacent_shifts_do_not_read_same_sample` |
| TRAP-24 | 可用升数不能整除保底权重 | 总量超分或漏分 | 整数最大余数法 | `src/greenhouse/irrigation_quota/analysis.py` | `tests/test_irrigation_quota.py::test_largest_remainder_conserves_shift_litres` |
| TRAP-26 | 计量单旧修订后上传 | 用量证据被覆盖 | 最高修订生效，同修订冲突停用 | `src/greenhouse/watering_ledger/analysis.py` | `tests/test_watering_ledger.py::test_stale_meter_revision_never_replaces_latest` |
| TRAP-31 | 干燥紧急程度对数极端 | 指数溢出 | 区分正负号稳定求值 | `src/greenhouse/moisture_band/analysis.py` | `tests/test_moisture_band.py::test_sigmoid_dryness_safe_for_extreme_candidates` |
| TRAP-32 | 历史特征近乎常量 | 方差严重抵消 | 围绕训练期均值累加平方 | `src/greenhouse/evapotranspiration/analysis.py` | `tests/test_evapotranspiration.py::test_stable_variance_on_near_constant_history` |
| TRAP-42 | 根区记录业务日期较早但延迟上传 | 未来发布数据改变历史训练 | 同时限定业务日和发布时间 | `src/greenhouse/rootzone_history/analysis.py` | `tests/test_rootzone_history.py::test_visible_dates_prevent_retrospective_leakage` |
| TRAP-43 | 无剩余有效校准集 | 空桶误报正常 | 保留空状态并停止拨水 | `src/greenhouse/moisture_band/analysis.py` | `tests/test_moisture_band.py::test_empty_validation_keeps_uncertainty_unknown` |
| TRAP-44 | 当日光照超出历史范围 | 超自然幅度仍生成授权 | 超分布工况显式挂起 | `src/greenhouse/moisture_band/analysis.py` | `tests/test_moisture_band.py::test_shift_distance_disables_high_demand` |
| TRAP-53 | 推断批并入超常工况 | 训练缩放被新批次改变 | 固定训练期统计量 | `src/greenhouse/evapotranspiration/analysis.py` | `tests/test_evapotranspiration.py::test_one_zone_prediction_is_independent_of_batch_population` |
