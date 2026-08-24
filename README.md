# A Share Intraday Radar

本地运行的 A 股个股盘中买点雷达，用于跟踪 AI 硬件产业链股票池。

## 启动

Windows 使用：

```powershell
.\start.ps1
.\stop.ps1
```

`start.ps1` 会异步提交后台启动任务后立即退出，双击时终端只会短暂闪现，不会等待服务完成就绪检查。

需要双击后无窗口启动时使用 `start_hidden.vbs`。它通过项目 `pythonw.exe` 直接调用 `manage.py`，不会创建 PowerShell 或 Windows Terminal 窗口；管理输出写入 `.radar.launch.log`。

Linux / VPS 使用：

```sh
./start.sh
./stop.sh
```

根目录 `manage.py` 统一提供 `start`、`stop`、`restart` 和 `status`。启动脚本不会创建虚拟环境、安装依赖或回退到系统 Python；缺少项目 `.venv` 时会明确报错退出。

```powershell
.\.venv\Scripts\python.exe manage.py status
.\.venv\Scripts\python.exe manage.py restart
```

控制器会记录 PID 和日志，并通过项目身份接口与 PID 文件识别进程，避免误停其他 Python 服务。日志文件为 `.radar.out.log` 和 `.radar.err.log`。

默认使用 `8030` 端口；如果该端口被无法接管的当前项目旧实例占用，控制器会自动选择后续空闲端口，并在启动信息中打印实际访问地址。停止命令会根据 PID 文件停止实际端口上的实例。

```powershell
cd D:\codex_project\a_share_intraday_radar
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.ps1
```

默认访问地址：`http://127.0.0.1:8030`

可覆盖端口：

```powershell
$env:WEB_PORT = "8031"
.\start.ps1
```

## 功能

- 按行业分组展示股票池。
- 每 60 秒刷新实时行情。
- 计算 MA5/10/20/60、RSI14、量比、均线乖离、20/60 日位置。
- 按 MA5/MA10 规则标记 `买入`、`减仓`、`剔除`、`观察`，悬停信号可查看触发原因。
- 手动刷新和本地缓存兜底。

本工具只做信息监控，不连接券商，不自动下单。

# 个股 MA5/MA10 信号系统

信号按风险优先级依次判断：`剔除 → 减仓 → 买入 → 观察`。

| 信号 | 触发条件 | 动作 |
| :--- | :--- | :--- |
| **买入** | 当前价 > MA5、MA5斜率 > 0、MA10斜率 > 0、MA5 > MA10 | 按计划执行 |
| **减仓** | 当前价 < MA5，或 MA5斜率 <= 0 | 先减 1/2 |
| **剔除** | 当前价 < MA10，或 MA5斜率 < 0 且 MA10斜率 < 0 | 清仓或移出候选 |
| **观察** | 未满足以上条件，或均线数据未补全 | 等待条件确认 |

MA20、MA60、RSI、量比等指标继续保留在界面中作为参考，但不参与信号判定。
