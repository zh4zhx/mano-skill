# Mano skill

Desktop GUI automation driven by natural language. Captures screenshots, analyzes them with a hybrid vision model, and executes the returned actions on the local machine — click, type, scroll, drag, and more. Supports fully on-device local mode and cloud mode.

> **Skill:** Also available as a Claude Code / OpenClaw skill at [clawhub.ai/hanningwang/mano-cua](https://clawhub.ai/hanningwang/mano-cua) and in the [`skill/`](skill/) directory of this repo.

## How It Works

```
User ──► Local client ──► Cloud Server ──► Local client executes action
              │                         │
         screenshot               model selection
                                       │
                            ┌──────────┴──────────┐
                            │                     │
                       Mano Model           Claude CUA Model
                    (fast, lightweight)    (complex reasoning)
```

At each step, mano-cua captures the current screenshot and sends it along with the task description to the cloud server. The server analyzes the task and **automatically selects the most suitable model**:

- **Mano Model** — optimized for straightforward, repetitive GUI tasks. Low latency, high throughput. Ideal for simple clicks, form filling, and navigation.
- **Claude CUA (Computer Use Agent)** — handles tasks that require deeper visual understanding and multi-step reasoning. Used when the task involves complex layouts, ambiguous UI elements, or decision-making.

The server evaluates task complexity in real time and routes accordingly, balancing speed and accuracy.

## Installation

**macOS / Linux (Homebrew):**

```bash
brew install Mininglamp-AI/tap/mano-cua

# Update to latest version
brew upgrade Mininglamp-AI/tap/mano-cua
```

**Windows:**

Download the latest `mano-cua-windows.zip` from [GitHub Releases](https://github.com/Mininglamp-AI/mano-skill/releases), extract it, and add the folder to your `PATH`.

**From source on macOS:**

```bash
./install.sh
```

## Usage

```bash
# Run a task
mano-cua run "your task description"

# Run with options (minimize UI panel and set max steps)
mano-cua run --minimize --max-steps 10 "task"

# Open a URL in the browser before starting the task
mano-cua run --url "https://example.com" "task"

# Open an app before starting the task
mano-cua run --app "Notes" "task"

# Start the persistent local inference service
mano-cua local start

# Start the service for LAN access
mano-cua local start --host 0.0.0.0

# Check or stop the persistent local inference service
mano-cua local status
mano-cua local stop

# Run in local mode (on-device inference, macOS Apple Silicon only)
mano-cua run --local "task"

# Persist task screenshots for debugging
mano-cua run --screenshot-cache-dir /tmp/mano-cua-cache "task"

# Stop the current running task
mano-cua stop
```

> **Note:** Only one task can run at a time per device. If you need to start a new task, first stop the current one with `mano-cua stop`.

## Local Mode

Runs [Mano-P](https://huggingface.co/Mininglamp-2718/Mano-P) entirely on-device via MLX. No data leaves the machine. Requires macOS with Apple Silicon (M1+).

```bash
# Setup
mano-cua check
mano-cua install-sdk
mano-cua install-model
mano-cua local start

# Optional: allow other devices on your LAN to reach the local service
mano-cua local start --host 0.0.0.0

# Run
mano-cua run --local --url "https://www.google.com" "click the search box, type openai, click search"
```

## Examples

```bash
# Local mode (all inference on-device, no data leaves the machine)
mano-cua local start
mano-cua run --local --url "https://www.google.com" --minimize "click the search box, type openai, click search, click the first result"
mano-cua run --local --app "Notes" "create a new note and type hello world"

# Local mode service reachable from your LAN
mano-cua local start --host 0.0.0.0
mano-cua local status

# Run GUI automation on this machine, but use a remote local model service on your LAN
mano-cua run --local \
  --local-service-host 192.168.1.20 \
  --local-service-token YOUR_PASSPHRASE \
  "Open Notes and create a new note"

# Cloud mode
mano-cua run "Open Notes and create a new note titled Meeting Summary"
mano-cua run --minimize --max-steps 20 "Search for AI news in the browser and show the first result"

# Cloud mode with --app or --url
mano-cua run --app "Microsoft Outlook" "Create a calendar event for Friday 20:00 named Team Meeting"
mano-cua run --url "https://www.flightaware.com/" "Compare available plans for the AeroAPI"

# Expected-result validation and screenshot cache
mano-cua run --expected-result "Bluetooth settings page is visible" "Open System Settings and go to Bluetooth"
mano-cua run --screenshot-cache-dir /tmp/mano-cua-cache "Open System Settings and go to Bluetooth"

# More examples
mano-cua run "Open WeChat and tell FTY that the meeting is postponed"
mano-cua run "Search for AI news in Xiaohongshu and show the first post"

# Stop the current task
mano-cua stop

# Stop the persistent local inference service
mano-cua local stop
```

`run --local` now requires the local inference service to be running first. If it is not running, the CLI will ask you to start it with `mano-cua local start`.

To expose the service to other devices on your local network, start it with `mano-cua local start --host 0.0.0.0`. The CLI keeps local requests on `127.0.0.1`, and `mano-cua local status` will show both the bind host and the local access address.

To expose the service with your own memorable passphrase instead of a generated token, start it with `mano-cua local start --token your-passphrase` (you can combine this with `--host 0.0.0.0`).

Requests from the same machine over `127.0.0.1` or `::1` do not need a token. Requests from other devices on the LAN still require the configured token/passphrase.

To run automation on one machine while using a model service hosted on another machine in the same LAN, use `run --local` with `--local-service-host`, optional `--local-service-port`, and `--local-service-token`. The value passed to `--local-service-token` can be either the generated token or your custom passphrase. The remote host should be the LAN IP of the machine running `mano-cua local start --host 0.0.0.0`.

## Supported Actions

click · type · hotkey · scroll · drag · mouse move · screenshot · wait · app launch · URL open

## Permissions

Screen Recording and Accessibility (Keyboard/Mouse control) permissions are required. Grant these in **System Preferences > Privacy & Security** before running.

## Status Panel

A small UI panel is displayed on the top-right corner of the screen to track and manage the current session status.

## Debugging

Use `--screenshot-cache-dir` to persist the task-start screenshot, the last screenshot of each step, and the task-end screenshot together with an `index.json` timeline. This is useful for replaying failures and inspecting what the model saw at each step.

## macOS Utility

`mac_silent_install.py` can silently install `.dmg` and `.pkg` payloads before handing control back to `mano-cua`.

```bash
python3 mac_silent_install.py \
  --install-package-path "/tmp/demo.dmg" \
  --app-path "/Applications/Demo.app" \
  --udid "demo-local" \
  --verbose
```

## Safety & Consent

- Sensitive or irreversible actions trigger a confirmation prompt — the agent pauses and waits for explicit user approval before proceeding.
- Screenshots are captured and applications may be started or closed during the session. **Avoid exposing apps with sensitive or critical data** while a task is running.
- For privacy-sensitive tasks, **local mode (`--local`)** runs inference entirely on-device with zero network calls.

## Important Notes

- **Do not use the mouse or keyboard during the task.** Manual input while mano-cua is running may cause unexpected behavior.
- **Multiple displays:** only the primary display is used. All mouse movements, clicks, and screenshots are restricted to that display.

## Platform Support

macOS is the preferred and most tested platform. Adaptations for Windows and Linux are not yet fully completed — minor issues are expected.

## License

MIT-0
