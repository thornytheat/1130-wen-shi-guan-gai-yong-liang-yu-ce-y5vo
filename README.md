# 温室灌溉用量预测

面向温室值班的本地工作台。内置业务样例覆盖温室灌溉时序回归、缺测校核与分区用水限额。样例采用确定性构造，适合复现实验和核查边界行为。

## 启动

```sh
docker compose up --build -d
```

打开 `http://127.0.0.1:18209/` 查看灌溉配水单。左侧六个入口可展开运行证据。调整「班次配水额度」，点击「重排配水」比较处置结果。结束后执行 `docker compose down --remove-orphans`。

## 独立业务模块

- 阀门遥测 `valve_telemetry`
- 根区水分 `rootzone_history`
- 蒸腾回归 `evapotranspiration`
- 偏差检验 `moisture_band`
- 分区拨水 `irrigation_quota`
- 农事账目 `watering_ledger`

## 查看运行结果

- `GET /api/overview` 返回默认运行及其指纹。
- `POST /api/scenario` 接收 `{"capacity": 3}`。入口接受 1–100 的整数，应用样例时使用该业务额度。
- `GET /api/stages/watering_ledger` 查看该环节的独立证据，支持 `?capacity=3`。

```sh
docker compose exec -T app python -m greenhouse.delivery evaluate --capacity 3
docker compose exec -T app pytest -q
```

数据和模型约定见 [业务契约](docs/SPEC.md)。模块、例外规则与验证入口见 [业务深度](docs/DEPTH.md)。
