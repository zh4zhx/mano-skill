---
name: mano-cua
description: Use when 需要通过 VLA 模型执行桌面 GUI 自动化，任务依赖视觉识别与屏幕交互，且目标应用没有可用 API 或 CLI 时。
---

# mano-cua

由自然语言驱动的桌面 GUI 自动化。它会截取当前屏幕截图，混合视觉模型分析截图，并在机器上执行返回的操作，包括点击、输入、滚动、拖拽等。

## 使用要求

- 具备**图形桌面环境**的系统（macOS）
- `python3` 可用
- 首次使用前已执行本目录下的 `install.sh`

### 安装

在项目目录下执行安装脚本：

```bash
cd /Users/test/Documents/mano-skill
./install.sh
```

`install.sh` 会执行这些事情：

- 创建或复用当前目录下的 `.venv`
- 从 `requirements.txt` 安装依赖
- 默认在 `/opt/homebrew/bin/mano-cua` 生成启动脚本
- 启动脚本实际执行的是 `.venv/bin/python -m visual.vla`

常用安装参数：

```bash
# 安装到自定义 bin 目录
BIN_DIR="$HOME/.local/bin" ./install.sh

# 跳过 pip 升级
SKIP_PIP_UPGRADE=1 ./install.sh

# 复用现有依赖，只刷新 launcher
SKIP_DEPENDENCY_INSTALL=1 ./install.sh
```

说明：

- 如果你的 `PATH` 不包含安装目录，请使用完整路径运行 `mano-cua`，或者把对应目录加入 `PATH`
- 如果后续移动了项目目录，需要重新执行 `./install.sh` 刷新 launcher 中固化的项目路径

## 用法

```bash
usage: vla.py run [-h] [--expected-result EXPECTED_RESULT] [--minimize]
                  [--max-steps MAX_STEPS] [--local] [--model-path MODEL_PATH]
                  [--url URL] [--screenshot-cache-dir SCREENSHOT_CACHE_DIR]
                  [--app APP] task
```

常用命令：

```bash
# 运行一个任务
mano-cua run "your task description"

# 停止当前正在运行的任务
mano-cua stop
```

## 参数说明

### `--expected-result`

给任务提供一个“可观察、可验证”的目标结果，适合用于下面这些场景：

- 任务结束条件比较明确，需要 agent 帮你判断是否已经成功
- 任务目标是某个 UI 状态，而不是单纯执行一串操作
- 你希望复盘时能更清楚地区分“做了步骤”和“真正达成结果”

推荐写法：

- 写最终应该在屏幕上看到什么
- 尽量具体，不要只写 `success`、`done`、`完成`
- 优先描述可见元素、页面状态、弹窗、文本结果

示例：

```bash
mano-cua run --expected-result "个人中心弹窗出现" \
  "当前已经打开像素蛋糕软件，打开右侧的个人中心"
```

### `--screenshot-cache-dir`

把任务过程中的截图持久化到指定目录，适合用于：

- 排查失败步骤
- 回看模型每一步看到的画面
- 留存自动化执行证据

目录结构是：

- `<cache-dir>/<session-id-or-local-run>/index.json`
- `<cache-dir>/<session-id-or-local-run>/000_task-start.png`
- `<cache-dir>/<session-id-or-local-run>/001_step-01_<action>.png`
- `<cache-dir>/<session-id-or-local-run>/...`
- `<cache-dir>/<session-id-or-local-run>/NNN_task-end_<status>.png`

其中 `index.json` 会记录每张截图对应的步骤序号、动作描述、reasoning、时间戳等元信息。

示例：

```bash
mano-cua run --screenshot-cache-dir /tmp/mano-cua-cache \
  "打开系统设置并进入蓝牙页面"
```

### `--minimize`

启动后立即最小化右上角状态面板，适合不希望悬浮窗遮挡目标区域时使用。

### `--local`

使用本地模型推理，而不是云端会话。适合目标环境已经准备好本地模型权重和推理依赖时使用。

在当前实现里，本地模式依赖一个持久后台服务，需要先执行：

```bash
mano-cua local start
```

如果希望让局域网内其他设备也能访问这个本地服务，可以改为：

```bash
mano-cua local start --host 0.0.0.0
```

### `--model-path`

覆盖默认本地模型路径，通常和 `--local` 搭配使用。

### `--url`

在执行任务前先在默认浏览器中打开一个 URL，适合“先打开页面再交给 GUI 自动化继续”的场景。

### `--max-steps`

限制单次任务最多执行的步数。默认值由 CLI 传入，适合为长流程任务加安全边界。

## 示例

```bash
# 最简单的运行方式
mano-cua run "打开像素蛋糕软件"

# 带结果校验
mano-cua run --expected-result "像素蛋糕已经打开，页面里能看到项目页面图片信息" \
  "打开像素蛋糕软件，双击进入任意一个项目"

# 带截图缓存
mano-cua run --screenshot-cache-dir /tmp/mano-cua-cache \
  "打开像素蛋糕软件"

# 最小化状态面板
mano-cua run --minimize "打开像素蛋糕软件"

# 先打开 URL 再执行
mano-cua run --url "https://www.example.com" "在当前页面里点击登录按钮"

# 使用本地模型
mano-cua local start --model-path /absolute/path/to/model
mano-cua run --local --model-path /absolute/path/to/model "打开系统设置"

# 允许局域网访问本地推理服务
mano-cua local start --host 0.0.0.0 --model-path /absolute/path/to/model

# 使用自定义访问口令启动本地推理服务
mano-cua local start --host 0.0.0.0 --token my-passphrase --model-path /absolute/path/to/model

# 在当前机器执行 GUI 自动化，但把本地推理请求发给局域网另一台机器
mano-cua run --local \
  --local-service-host 192.168.1.20 \
  --local-service-token my-passphrase \
  "打开系统设置"

# 查看或停止本地推理后台服务
mano-cua local status
mano-cua local stop

# 停止当前任务
mano-cua stop
```

## `mac_silent_install.py` 使用说明

`mac_silent_install.py` 用于在 macOS 上静默安装 `.dmg/.pkg`，通常用于“先安装/更新应用，再交给 `mano-cua` 执行 GUI 自动化”的场景。

脚本位置：

- `/Users/test/Documents/mano-skill/mac_silent_install.py`

执行入口（建议在项目目录下）：

```bash
cd /Users/test/Documents/mano-skill
python3 mac_silent_install.py --help
```

### 参数

- `--payload-json`：直接传完整 JSON 字符串（最高优先级）
- `--payload-file`：传 JSON 文件路径
- `--install-package-path`：安装包路径或 URL（支持本地路径、`file://`、`http(s)://`）
- `--app-path`：目标 `.app` 路径（例如 `/Applications/pixcake-test.app`，可选）
- `--udid`：设备标识，用于安装缓存隔离（默认 `standalone-mac`）
- `--verbose`：打印 INFO 日志

脚本要求三种输入方式之一：

1. `--payload-json`
2. `--payload-file`
3. 至少提供 `--install-package-path`（可选追加 `--app-path/--udid`）

### 常见用法

```bash
# 1) 直接安装本地 dmg
python3 mac_silent_install.py \
  --install-package-path "/tmp/pixcake-test.dmg" \
  --app-path "/Applications/pixcake-test.app" \
  --udid "pixcake-local" \
  --verbose

# 2) 安装远程 pkg
python3 mac_silent_install.py \
  --install-package-path "https://example.com/pixcake.pkg" \
  --udid "pixcake-ci"

# 3) 使用 payload 文件（推荐给批量或流水线）
python3 mac_silent_install.py --payload-file /absolute/path/install_payload.json --verbose
```

`payload` 最小示例：

```json
{
  "installPackagePath": "/tmp/pixcake-test.dmg",
  "udId": "pixcake-local",
  "gp": {
    "appPath": "/Applications/pixcake-test.app"
  }
}
```

### 输出与退出码

- 标准输出为 JSON 结果，常见 `status`：
- `installed`：安装成功
- `skipped`：跳过（如 `already_installed`、`unsupported_package_format`、`missing_install_package_path`）
- `interrupted`：被中断
- `error`：安装失败
- 退出码：`installed/skipped` 返回 `0`，其余返回 `1`

### 行为说明与注意事项

- 支持的安装包格式仅 `.dmg` / `.pkg`，其他格式会返回 `skipped`
- `.dmg` 会挂载后复制 `.app` 到 `/Applications`（若 `--app-path` 不在 `/Applications/` 下，也会回退到 `/Applications`）
- `.pkg` 通过 `installer -pkg <file> -target /` 安装；权限不足时会失败，必要时请在具备权限的上下文执行
- 安装前会尝试结束目标应用进程，安装完成后会自动重启一次应用
- 安装包会先复制/下载到临时目录，执行结束会自动清理
- `already_installed` 缓存基于进程内 `udid + installPackagePath`，重启 Python 进程后缓存会重置

## 输出规范（必须）

当使用本 skill 生成执行方案时，必须提供“可直接执行”的脚本产物，而不是只给文字说明。

默认同时产出：

1. 一条可直接运行的 `mano-cua` 命令（one-liner）
2. 一个可执行的 `.sh` 脚本文件（建议放在工作区 `tmp/` 下）

脚本必须包含以下内容：

- `#!/usr/bin/env bash`
- `set -euo pipefail`
- `mano-cua stop || true`（启动前清理旧会话）
- `--expected-result`、`--screenshot-cache-dir` 和 `run "<task>"` 的完整参数
- `CACHE_DIR` 必须是绝对路径
- 命令输出必须重定向到绝对路径 `LOG_FILE`（`>> "$LOG_FILE" 2>&1`）
- 超时控制（默认最多 `300` 秒，即 `5` 分钟）
- 执行前先检测 PixCake 是否在运行；若在运行先杀掉
- 使用 `/Applications/pixcake-test.app/Contents/MacOS/pixcake &` 启动 PixCake
- 启动后默认等待 `10` 秒，再执行 mano-cua
- mano-cua 执行结束后（成功或失败）都要杀掉 PixCake
- 脚本写入后必须执行 `chmod +x <script_path>`，确保“一次生成、立即可执行”

推荐脚本模板：

```bash
#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="/Users/test/Documents/mano-skill"

CACHE_DIR="$REPO_ROOT/tmp/mano-shots-<case-id>"
LOG_DIR="$REPO_ROOT/tmp/mano-logs"
LOG_FILE="$LOG_DIR/<case-id>-mano-cua.log"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-300}"
PIXCAKE_BIN="/Applications/pixcake-test.app/Contents/MacOS/pixcake"
PIXCAKE_LAUNCH_SLEEP_SECONDS="${PIXCAKE_LAUNCH_SLEEP_SECONDS:-10}"
EXPECTED_RESULT="<可观察的期望结果>"
TASK="<完整任务描述，包含必要绝对路径>"

mkdir -p "$CACHE_DIR" "$LOG_DIR"

kill_pixcake_if_running() {
  if pgrep -f "$PIXCAKE_BIN" >/dev/null 2>&1; then
    pkill -f "$PIXCAKE_BIN" >> "$LOG_FILE" 2>&1 || true
    sleep 2
    if pgrep -f "$PIXCAKE_BIN" >/dev/null 2>&1; then
      pkill -9 -f "$PIXCAKE_BIN" >> "$LOG_FILE" 2>&1 || true
    fi
  fi
}

cleanup() {
  mano-cua stop >> "$LOG_FILE" 2>&1 || true
  kill_pixcake_if_running
}

trap cleanup EXIT

mano-cua stop >> "$LOG_FILE" 2>&1 || true
kill_pixcake_if_running
"$PIXCAKE_BIN" >> "$LOG_FILE" 2>&1 &
sleep "$PIXCAKE_LAUNCH_SLEEP_SECONDS"

set +e
perl -e 'alarm shift; exec @ARGV' "$TIMEOUT_SECONDS" \
  mano-cua run --expected-result "$EXPECTED_RESULT" \
  --minimize \
  --screenshot-cache-dir "$CACHE_DIR" \
  "$TASK" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
set -e

if [ "$EXIT_CODE" -ne 0 ]; then
  echo "mano-cua failed, exit=$EXIT_CODE, log=$LOG_FILE"
  exit "$EXIT_CODE"
fi
```

命名建议：

- Jira 验证：`tmp/mano-cua-<JIRA>-verify.sh`
- 通用任务：`tmp/mano-cua-<topic>-run.sh`

约束：

- `TASK` 中涉及素材路径时，必须使用绝对路径，避免文件选择器误选。
- 如果任务文本包含引号或特殊字符，生成脚本时应采用安全转义（例如单引号 heredoc）保证可执行性。
- `CACHE_DIR` 与 `LOG_FILE` 必须使用绝对路径，不允许相对路径。
- 默认超时 `5` 分钟；如需更长时间，允许通过环境变量覆盖，例如 `TIMEOUT_SECONDS=900 ./xxx.sh`。
- 默认等待 PixCake 启动 `10` 秒；如需调整，允许通过环境变量覆盖，例如 `PIXCAKE_LAUNCH_SLEEP_SECONDS=20 ./xxx.sh`。

## 支持的交互

click · type · hotkey · scroll · drag · mouse move · screenshot · wait · app launch · url direction

## 状态面板

屏幕右上角会显示一个小型 UI 面板，用于跟踪和管理当前会话状态。
- **控制：** 可以随时通过 UI 面板或执行 `mano-cua stop` 中止当前会话。

> **注意：** 每台设备同一时间只能运行一个任务。如果你要启动新任务，请先使用 `mano-cua stop` 停止当前任务。

## 重要说明

- **任务执行期间不要操作鼠标或键盘。** `mano-cua` 运行时的人工输入可能导致不可预期的行为。
- **多显示器场景：** 仅使用主显示器。所有鼠标移动、点击和截图都限制在主显示器范围内。
