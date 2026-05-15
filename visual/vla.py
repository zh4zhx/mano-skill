#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "requests",
#     "pynput",
#     "mss",
#     "customtkinter",
# ]
# ///

import os
import sys
import platform
import argparse
import subprocess
import time
import requests

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from visual.local_service import (
    LOCAL_SERVICE_DEFAULT_PORT,
    LOCAL_SERVICE_HOST,
    LocalInferenceService,
    LocalServiceError,
    build_local_service_url,
    delete_local_service_state,
    generate_local_service_token,
    get_local_service_connect_host,
    is_pid_alive,
    is_port_listening,
    load_local_service_state,
    make_local_service_headers,
    make_local_service_state,
    validate_local_service_token,
)


def stop_session():
    """Stop the current active session for this device"""
    from visual.config.visual_config import BASE_URL
    from visual.computer.computer_use_util import get_or_create_device_id

    device_id = get_or_create_device_id()

    try:
        resp = requests.post(
            f"{BASE_URL}/v1/devices/{device_id}/stop",
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get("ok"):
            print(f"Session stopped: {data.get('session_id')}")
            return 0
        else:
            print(f"No active session: {data.get('message')}")
            return 1
    except Exception as e:
        print(f"Failed to stop session: {e}")
        return 1


def _open_url_in_browser(url: str):
    """Open a URL in the default browser (cross-platform)."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", url])
        elif system == "Windows":
            subprocess.Popen(f'start "" "{url}"', shell=True)
        else:
            subprocess.Popen(["xdg-open", url])
        time.sleep(4)
    except Exception as e:
        print(f"Warning: failed to open URL: {e}")


def _open_app(app_name: str):
    """Open an application (cross-platform)."""
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", "-a", app_name])
        elif system == "Windows":
            subprocess.run(
                ["powershell", "-Command", f'Start-Process "{app_name}"'],
                shell=False, capture_output=True, text=True, timeout=10
            )
        else:
            subprocess.Popen([app_name])
        time.sleep(2)
    except Exception as e:
        print(f"Warning: failed to open app: {e}")


def _prepare_local_service_run(
    model_path: str = None,
    local_service_host: str = None,
    local_service_port: int = None,
    local_service_token: str = None,
):
    """Resolve the local inference service endpoint and requested model path."""
    if local_service_host:
        if not local_service_token:
            raise LocalServiceError("--local-service-token is required when --local-service-host is set.")
        remote_service_state = make_local_service_state(
            host=local_service_host,
            port=local_service_port or LOCAL_SERVICE_DEFAULT_PORT,
            token=local_service_token,
            use_connect_host=False,
        )
        service_state = ensure_local_service_ready(
            requested_model_path=None,
            service_state=remote_service_state,
            require_matching_model_path=False,
        )
        return service_state, None

    resolved_path = _resolve_local_model_path(model_path)
    service_state = ensure_local_service_ready(
        requested_model_path=resolved_path,
        require_matching_model_path=True,
    )
    return service_state, resolved_path


def run_task(task: str, expected_result: str = None, minimize: bool = False,
             max_steps: int = None, local: bool = False, model_path: str = None,
             url: str = None, app: str = None, screenshot_cache_dir: str = None,
             local_service_host: str = None, local_service_port: int = None,
             local_service_token: str = None):
    """Run an automation task"""
    from visual.config.visual_config import BASE_URL, AUTOMATION_CONFIG, API_HEADERS
    from visual.computer.computer_use_util import get_or_create_device_id

    if local:
        try:
            service_state, requested_model_path = _prepare_local_service_run(
                model_path=model_path,
                local_service_host=local_service_host,
                local_service_port=local_service_port,
                local_service_token=local_service_token,
            )
        except LocalServiceError as exc:
            print(f"Error: {exc}")
            return 1
    # Open app/URL before starting (both modes)
    if app:
        _open_app(app)
    if url:
        _open_url_in_browser(url)

    if local:
        try:
            from visual.agents.local_service import LocalServiceAgent
            agent = LocalServiceAgent(
                task_instruction=task,
                expected_result=expected_result,
                requested_model_path=requested_model_path,
                service_state=service_state,
            )
        except Exception as e:
            print(f"Error: {e}")
            return 1
    else:
        # --- Cloud mode (default, existing behavior) ---
        device_id = get_or_create_device_id()
        try:
            body = {
                "task": task,
                "device_id": device_id,
                "platform": platform.system()
            }
            if expected_result:
                body["expected_result"] = expected_result

            resp = requests.post(
                f"{BASE_URL}/v1/sessions",
                json=body,
                headers=API_HEADERS,
                timeout=AUTOMATION_CONFIG["SESSION_TIMEOUT"]
            )
            if resp.status_code == 409:
                print(f"Error: Another task is already running on this device.")
                print(f"Use 'mano-cua stop' to stop it first.")
                return 1

            resp.raise_for_status()
            data = resp.json()

            session_id = data["session_id"]
            print(f"Session created: {session_id}")

        except Exception as e:
            print(f"Failed to create session: {e}")
            return 1

        from visual.agents.cloud import CloudAgent
        agent = CloudAgent(server_url=BASE_URL, session_id=session_id, device_id=device_id)

    # Initialize UI and run
    from visual.view_model.task_view_model import TaskViewModel

    view_model = TaskViewModel()

    if not view_model.init_task(
        task,
        agent,
        expected_result=expected_result,
        max_steps=max_steps,
        screenshot_cache_dir=screenshot_cache_dir,
    ):
        print("Failed to initialize visualization overlay.")
        # Run task directly without UI
        view_model.model.init_task(
            task,
            agent,
            expected_result=expected_result,
            max_steps=max_steps,
            screenshot_cache_dir=screenshot_cache_dir,
        )
        view_model.model.run_automation_task()
        return 0 if view_model.model.state.status == "completed" else 1

    # Start minimized before the task thread begins so the first shortcut reaches the target app.
    if minimize and view_model.view and view_model.view._ui_initialized:
        view_model.view.minimize_and_restore_focus()

    # Run task
    success = view_model.run_task()
    # Clean up resources
    view_model.close()
    return 0 if success else 1


# ========== Config / Check / Install subcommands ==========

def cmd_config(args):
    """Manage persistent config (~/.mano/config.json)"""
    from visual.config.user_config import get_config, set_config, list_config

    if args.config_list:
        list_config()
        return 0
    if args.get:
        val = get_config(args.get)
        if val is not None:
            print(val)
        else:
            print(f"(not set)")
        return 0
    if args.set:
        if len(args.set) != 2:
            print("Usage: mano-cua config --set KEY VALUE")
            return 1
        set_config(args.set[0], args.set[1])
        print(f"Set {args.set[0]} = {args.set[1]}")
        # Setting python-path: verify deps in that environment
        if args.set[0] == "python-path":
            py = args.set[1]
            if os.path.isfile(py):
                result = subprocess.run(
                    [py, "-c", "from vlm_service import custom_generate; from cider import is_available; import torch; print('OK')"],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    set_config("sdk-installed", "true")
                    print("  Dependencies verified. sdk-installed = true")
                else:
                    err = result.stderr.strip().split("\n")[-1] if result.stderr else "unknown error"
                    print(f"  Warning: dependencies missing in that environment — {err}")
                    print("  You may need to install: mlx-vlm, torch, cider (compiled from git)")
            else:
                print(f"  Warning: {py} not found")
        # Setting default-model-path: verify model exists
        if args.set[0] == "default-model-path":
            expanded = os.path.expanduser(args.set[1])
            if os.path.isdir(expanded):
                set_config("model-installed", "true")
                print(f"  Model verified. model-installed = true")
            else:
                print(f"  Warning: path not found — {expanded}")
        return 0

    print("Usage: mano-cua config [--list | --get KEY | --set KEY VALUE]")
    return 1


def _load_running_local_service_state(service_state: dict = None) -> dict:
    state = service_state or load_local_service_state()
    if not state:
        raise LocalServiceError("Local service is not running. Start it with: mano-cua local start")

    pid = state.get("pid")
    host = state.get("connect_host") or get_local_service_connect_host(state.get("host"))
    port = int(state.get("port") or LOCAL_SERVICE_DEFAULT_PORT)
    explicit_service_target = service_state is not None

    if explicit_service_target:
        if not is_port_listening(host, port):
            raise LocalServiceError(
                f"Local service at {host}:{port} is not reachable. "
                "Make sure the remote machine is running `mano-cua local start --host 0.0.0.0` "
                "and that the host, port, and token are correct."
            )
        return state

    if pid and not is_pid_alive(pid):
        delete_local_service_state()
        raise LocalServiceError("Local service is not running. Start it with: mano-cua local start")
    if not is_port_listening(host, port):
        if pid:
            delete_local_service_state()
        raise LocalServiceError("Local service is not running. Start it with: mano-cua local start")
    return state


def _local_service_request(method: str, path: str, payload: dict = None, timeout: int = 30, service_state: dict = None) -> dict:
    state = _load_running_local_service_state(service_state=service_state)
    headers = make_local_service_headers(state.get("token"))
    url = build_local_service_url(path, state)
    host = state.get("connect_host") or get_local_service_connect_host(state.get("host"))
    port = int(state.get("port") or LOCAL_SERVICE_DEFAULT_PORT)

    try:
        response = requests.request(
            method=method,
            url=url,
            json=payload or {},
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        if service_state is not None:
            raise LocalServiceError(
                f"Local service at {host}:{port} is unavailable. "
                "Make sure the remote machine is reachable and the service has finished loading the model."
            ) from exc
        raise LocalServiceError("Local service is unavailable. Restart it with: mano-cua local stop && mano-cua local start") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise LocalServiceError("Local service returned an invalid response.") from exc

    if not response.ok or not data.get("ok", False):
        raise LocalServiceError(data.get("detail") or f"Local service request failed: HTTP {response.status_code}")
    return data


def ensure_local_service_ready(requested_model_path: str = None, service_state: dict = None, require_matching_model_path: bool = True) -> dict:
    state = _load_running_local_service_state(service_state=service_state)
    normalized_requested = None
    if requested_model_path:
        normalized_requested = os.path.abspath(os.path.expanduser(requested_model_path))

    data = _local_service_request("GET", "/v1/local/status", timeout=10, service_state=state)
    service_model_path = os.path.abspath(os.path.expanduser(data.get("model_path") or state.get("model_path") or ""))
    if require_matching_model_path and not normalized_requested:
        raise LocalServiceError("Requested model path is required to validate the local inference service.")
    if require_matching_model_path and service_model_path != normalized_requested:
        raise LocalServiceError(
            f"Local service is running with model '{service_model_path}'. Stop it and restart with '{normalized_requested}'."
        )
    if not data.get("ready"):
        raise LocalServiceError("Local service is not ready yet. Wait for model loading to finish or restart it.")
    merged = dict(state)
    merged.update(data)
    return merged


def _resolve_local_service_python() -> str:
    from visual.config.user_config import get_config

    python_path = get_config("python-path")
    if python_path and os.path.isfile(python_path):
        return python_path
    return sys.executable


def _resolve_local_model_path(model_path: str = None) -> str:
    from visual.config.user_config import get_config

    resolved_path = model_path or get_config("default-model-path")
    if not resolved_path:
        raise LocalServiceError("No model path configured. Use --model-path or set default-model-path first.")
    resolved_path = os.path.abspath(os.path.expanduser(resolved_path))
    if not os.path.isdir(resolved_path):
        raise LocalServiceError(f"Model path not found: {resolved_path}")
    return resolved_path


def cmd_local_start(args):
    """Start the persistent local inference service."""
    model_path = _resolve_local_model_path(args.model_path)
    host = args.host or LOCAL_SERVICE_HOST
    port = args.port or LOCAL_SERVICE_DEFAULT_PORT

    existing = load_local_service_state()
    existing_connect_host = existing.get("connect_host") or get_local_service_connect_host(existing.get("host")) if existing else None
    if existing and is_pid_alive(existing.get("pid")) and is_port_listening(existing_connect_host, int(existing.get("port") or port)):
        existing_model_path = os.path.abspath(os.path.expanduser(existing.get("model_path") or ""))
        existing_host = existing.get("host") or LOCAL_SERVICE_HOST
        existing_port = int(existing.get("port") or port)
        if existing_model_path == model_path and existing_host == host and existing_port == port:
            print(f"Local service already running on {existing.get('host') or LOCAL_SERVICE_HOST}:{existing.get('port') or port}")
            if existing_connect_host and existing_connect_host != existing.get("host"):
                print(f"Local access: {existing_connect_host}:{existing.get('port') or port}")
            print(f"Model: {existing_model_path}")
            return 0
        if existing_model_path == model_path:
            print("Error: Local service is already running with a different host or port.")
            print(f"Current: {existing_host}:{existing_port}")
            print(f"Requested: {host}:{port}")
            print("Run: mano-cua local stop")
            return 1
        print("Error: Local service is already running with a different model.")
        print(f"Current: {existing_model_path}")
        print(f"Requested: {model_path}")
        print("Run: mano-cua local stop")
        return 1

    if existing:
        delete_local_service_state()

    token = validate_local_service_token(args.token) if args.token else generate_local_service_token()

    if args.foreground:
        service = LocalInferenceService(model_path=model_path, host=host, port=port, token=token)
        service.preload()
        service.persist_state()
        print(f"Local service ready on {host}:{port}")
        connect_host = get_local_service_connect_host(host)
        if connect_host != host:
            print(f"Local access: {connect_host}:{port}")
        print(f"Model: {model_path}")
        service.serve_forever()
        return 0

    python_exec = _resolve_local_service_python()
    cmd = [
        python_exec,
        "-m",
        "visual.vla",
        "local",
        "start",
        "--foreground",
        "--port",
        str(port),
        "--host",
        host,
        "--model-path",
        model_path,
    ]
    env = os.environ.copy()
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = src_dir + ((":" + env.get("PYTHONPATH", "")) if env.get("PYTHONPATH") else "")
    env["MANO_LOCAL_SERVICE_TOKEN"] = token

    with open(os.path.expanduser("~/.mano/local-service.log"), "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            env=env,
            cwd=src_dir,
        )

    deadline = time.time() + 180
    while time.time() < deadline:
        if process.poll() is not None:
            delete_local_service_state()
            print("Error: Local service failed to start. Check ~/.mano/local-service.log")
            return 1
        state = load_local_service_state()
        connect_host = state.get("connect_host") or get_local_service_connect_host(state.get("host")) if state else None
        if state and state.get("pid") == process.pid and is_port_listening(connect_host, int(state.get("port") or port)):
            try:
                status = _local_service_request("GET", "/v1/local/status", timeout=10)
            except LocalServiceError:
                time.sleep(1)
                continue
            if status.get("ready"):
                bind_host = status.get("host") or host
                print(f"Local service ready on {bind_host}:{status.get('port')}")
                status_connect_host = status.get("connect_host") or get_local_service_connect_host(bind_host)
                if status_connect_host != bind_host:
                    print(f"Local access: {status_connect_host}:{status.get('port')}")
                print(f"Model: {status.get('model_path')}")
                return 0
        time.sleep(1)

    print("Error: Timed out waiting for local service to become ready. Check ~/.mano/local-service.log")
    return 1


def cmd_local_status(args):
    """Show local inference service status."""
    state = load_local_service_state()
    if not state:
        print("Local service: not running")
        return 1

    pid = state.get("pid")
    host = state.get("host") or LOCAL_SERVICE_HOST
    connect_host = state.get("connect_host") or get_local_service_connect_host(host)
    port = int(state.get("port") or LOCAL_SERVICE_DEFAULT_PORT)
    if not is_pid_alive(pid) or not is_port_listening(connect_host, port):
        delete_local_service_state()
        print("Local service: not running")
        return 1

    try:
        data = _local_service_request("GET", "/v1/local/status", timeout=10)
    except LocalServiceError as exc:
        print(f"Local service: unavailable ({exc})")
        return 1

    state_label = "ready/busy" if data.get("active_session") else "ready/idle"
    print(f"Local service: {state_label}")
    print(f"Host: {host}")
    if connect_host != host:
        print(f"Local access: {connect_host}")
    print(f"Port: {data.get('port')}")
    print(f"PID: {data.get('pid')}")
    print(f"Model: {data.get('model_path')}")
    print(f"Started at: {data.get('started_at')}")
    if data.get("active_session"):
        print(f"Active session: {data.get('active_session')} (client pid: {data.get('client_pid')})")
    if data.get("cleanup"):
        print(f"Cleanup: {data.get('cleanup')}")
    elif data.get("last_cleanup"):
        print(f"Cleanup: {data.get('last_cleanup')}")
    return 0


def cmd_local_stop(args):
    """Stop the persistent local inference service when idle."""
    state = load_local_service_state()
    if not state:
        print("Local service is not running.")
        return 0

    pid = state.get("pid")
    host = state.get("connect_host") or get_local_service_connect_host(state.get("host"))
    port = int(state.get("port") or LOCAL_SERVICE_DEFAULT_PORT)
    if not is_pid_alive(pid) or not is_port_listening(host, port):
        delete_local_service_state()
        print("Local service is not running.")
        return 0

    try:
        data = _local_service_request("POST", "/v1/local/shutdown", {}, timeout=10)
    except LocalServiceError as exc:
        print(f"Error: {exc}")
        return 1

    deadline = time.time() + 15
    while time.time() < deadline:
        current = load_local_service_state()
        if not current:
            print("Local service stopped.")
            return 0
        if not is_pid_alive(current.get("pid")):
            delete_local_service_state()
            print("Local service stopped.")
            return 0
        time.sleep(0.5)

    print("Local service is shutting down. Check `mano-cua local status` in a moment.")
    return 0


def cmd_check(args):
    """Check local mode dependencies"""
    from visual.config.user_config import get_config, set_config

    sdk_installed = get_config("sdk-installed") == "true"
    model_installed = get_config("model-installed") == "true"

    # If not marked, try to verify and update
    if not sdk_installed:
        python_path = get_config("python-path")
        py = python_path if python_path and os.path.isfile(python_path) else sys.executable
        result = subprocess.run(
            [py, "-c", "from vlm_service import custom_generate; from cider import is_available; import torch"],
            capture_output=True
        )
        if result.returncode == 0:
            set_config("sdk-installed", "true")
            sdk_installed = True

    if not model_installed:
        model_path = get_config("default-model-path")
        if model_path and os.path.isdir(os.path.expanduser(model_path)):
            set_config("model-installed", "true")
            model_installed = True

    # Report
    if sdk_installed:
        python_path = get_config("python-path") or sys.executable
        print(f"  sdk: OK (python: {python_path})")
    else:
        print("  sdk: NOT READY — run: mano-cua install-sdk")
        print("       or set python-path to an environment with deps:")
        print("       mano-cua config --set python-path /path/to/python")

    if model_installed:
        print(f"  model: OK ({get_config('default-model-path')})")
    else:
        print("  model: NOT READY — run: mano-cua install-model")
        print("       or set model path manually:")
        print("       mano-cua config --set default-model-path /path/to/model")

    if sdk_installed and model_installed:
        print("\nLocal mode is ready.")
        return 0
    else:
        print("\nLocal mode is not ready. Fix the items above.")
        return 1


def cmd_install_sdk(args):
    """Install local inference SDK into a persistent venv at ~/.mano/venv."""
    import subprocess

    venv_dir = os.path.expanduser("~/.mano/venv")
    venv_python = os.path.join(venv_dir, "bin", "python3")

    # Create persistent venv if not exists
    if not os.path.isfile(venv_python):
        print(f"  Creating persistent venv at {venv_dir}...")
        subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)

    pip_cmd = [venv_python, "-m", "pip"]

    # 1. Base deps (same as brew venv — needed for mano-cua to run)
    print(f"  Installing base dependencies...")
    result = subprocess.run(pip_cmd + ["install", "requests", "mss", "pynput", "customtkinter", "Pillow", "huggingface_hub"], capture_output=True)
    if result.returncode != 0:
        print(f"  Base dependencies installation failed.")
        return 1

    # 2. mlx-vlm (includes mlx, transformers, etc.)
    print(f"  Installing mlx-vlm...")
    result = subprocess.run(pip_cmd + ["install", "mlx-vlm"])
    if result.returncode != 0:
        print(f"  mlx-vlm installation failed.")
        return 1

    # 3. torch (required by vlm_service)
    print(f"  Installing torch...")
    result = subprocess.run(pip_cmd + ["install", "torch"])
    if result.returncode != 0:
        print(f"  torch installation failed.")
        return 1

    # 4. cider — always from GitHub (must compile C++ extension)
    print(f"  Installing cider from GitHub (compiling C++ extension)...")
    result = subprocess.run(pip_cmd + ["install", "--force-reinstall", "--no-deps", "git+https://github.com/Mininglamp-AI/cider.git"])
    if result.returncode != 0:
        print(f"  cider installation failed. Ensure CMake >= 3.27 and Xcode CLI tools are installed.")
        return 1
    print(f"  cider: installed")

    # Set python-path to the persistent venv
    from visual.config.user_config import set_config
    set_config("python-path", venv_python)
    set_config("sdk-installed", "true")

    print(f"\nSDK ready. Python path set to: {venv_python}")
    print("Run 'mano-cua check' to verify.")
    return 0


def cmd_install_model(args):
    """Download model weights from HuggingFace"""
    import subprocess

    model_name = args.name or "Mininglamp-2718/Mano-P"
    model_dir = os.path.expanduser("~/.mano/models/Mano-P")

    print(f"Downloading model: {model_name}\n")
    print("Option 1: Download from webpage")
    print(f"  https://huggingface.co/{model_name}/tree/main/w8a16")
    print(f"  Download all files, then:")
    print(f"  mano-cua config --set default-model-path /path/to/w8a16\n")
    print("Option 2: Download via CLI (requires HuggingFace token)")
    print("  1. Create a token at https://huggingface.co/settings/tokens ")
    print("  2. Run: hf auth login")
    print(f"  3. Downloading now...\n")

    result = subprocess.run(
        ["hf", "download", model_name, "--include", "w8a16/*", "--local-dir", model_dir]
    )
    if result.returncode != 0:
        print(f"\nDownload failed. Make sure you are logged in:")
        print(f"  hf auth login")
        print(f"  Then run: mano-cua install-model")
        print(f"\nOr download manually and set path:")
        print(f"  mano-cua config --set default-model-path /path/to/model")
        return 1

    model_path = os.path.join(model_dir, "w8a16")
    if not os.path.isdir(model_path):
        model_path = model_dir

    from visual.config.user_config import set_config
    set_config("default-model-path", model_path)
    set_config("model-installed", "true")
    print(f"\nModel ready: {model_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="VLA Desktop Automation Client")
    subparsers = parser.add_subparsers(dest="command")

    # --- run ---
    run_parser = subparsers.add_parser("run", help="Run an automation task")
    run_parser.add_argument("task", help="Task description")
    run_parser.add_argument("--expected-result", help="Expected result description for validation", default=None)
    run_parser.add_argument("--minimize", help="Start with minimized UI panel", action="store_true", default=False)
    run_parser.add_argument("--max-steps", help="Maximum number of steps", type=int, default=100)
    run_parser.add_argument("--local", help="Use local model inference (MLX)", action="store_true", default=False)
    run_parser.add_argument("--model-path", help="Local model weights path (overrides config)", default=None)
    run_parser.add_argument("--local-service-host", help="Remote local inference service host for --local mode", default=None)
    run_parser.add_argument("--local-service-port", help=f"Remote local inference service port (default: {LOCAL_SERVICE_DEFAULT_PORT})", type=int, default=LOCAL_SERVICE_DEFAULT_PORT)
    run_parser.add_argument("--local-service-token", help="Remote local inference service token for --local mode", default=None)
    run_parser.add_argument("--url", help="Open URL in browser before starting task", default=None)
    run_parser.add_argument(
        "--screenshot-cache-dir",
        help="Persist task-start, per-step, and task-end screenshots under the given directory",
        default=None,
    )
    run_parser.add_argument("--app", help="Open app before starting task (use macOS app name, e.g. 'Notes', 'Safari', 'Google Chrome')", default=None)

    # --- stop ---
    subparsers.add_parser("stop", help="Stop the current running task")

    # --- local service management ---
    local_parser = subparsers.add_parser("local", help="Manage the persistent local inference service")
    local_subparsers = local_parser.add_subparsers(dest="local_command")

    local_start_parser = local_subparsers.add_parser("start", help="Start the persistent local inference service")
    local_start_parser.add_argument("--model-path", help="Local model weights path (overrides config)", default=None)
    local_start_parser.add_argument("--host", help=f"Bind host (default: {LOCAL_SERVICE_HOST}; use 0.0.0.0 for LAN access)", default=LOCAL_SERVICE_HOST)
    local_start_parser.add_argument("--port", help=f"Service port (default: {LOCAL_SERVICE_DEFAULT_PORT})", type=int, default=LOCAL_SERVICE_DEFAULT_PORT)
    local_start_parser.add_argument("--token", help="Custom access token/passphrase for the local inference service", default=None)
    local_start_parser.add_argument("--foreground", help="Run the local service in the foreground", action="store_true", default=False)
    local_subparsers.add_parser("status", help="Show persistent local inference service status")
    local_subparsers.add_parser("stop", help="Stop the persistent local inference service when idle")

    # --- config ---
    config_parser = subparsers.add_parser("config", help="Manage persistent config")
    config_parser.add_argument("--list", dest="config_list", action="store_true", help="List all config values")
    config_parser.add_argument("--get", metavar="KEY", help="Get a config value")
    config_parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"), help="Set a config value")

    # --- check ---
    subparsers.add_parser("check", help="Check local mode dependencies")

    # --- install-sdk ---
    subparsers.add_parser("install-sdk", help="Install local inference SDK (mlx-vlm + cider)")

    # --- install-model ---
    install_parser = subparsers.add_parser("install-model", help="Download model from HuggingFace")
    install_parser.add_argument("name", nargs="?", help="Model name (default: Mininglamp-2718/Mano-P)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "stop":
        # Write stop flag (picked up by local task loop between steps)
        flag = os.path.expanduser("~/.mano/stop.flag")
        os.makedirs(os.path.dirname(flag), exist_ok=True)
        open(flag, "w").close()
        print("Stop signal sent. Local task will stop after current step completes.")
        # Also attempt cloud session stop
        ret = stop_session()
        return ret

    if args.command == "local":
        if args.local_command == "start":
            token = os.environ.get("MANO_LOCAL_SERVICE_TOKEN")
            if args.foreground:
                if not token:
                    print("Error: MANO_LOCAL_SERVICE_TOKEN is required for foreground local service mode.")
                    return 1
                service = LocalInferenceService(
                    model_path=_resolve_local_model_path(args.model_path),
                    host=args.host or LOCAL_SERVICE_HOST,
                    port=args.port,
                    token=token,
                )
                service.preload()
                service.persist_state()
                service.serve_forever()
                return 0
            return cmd_local_start(args)
        if args.local_command == "status":
            return cmd_local_status(args)
        if args.local_command == "stop":
            return cmd_local_stop(args)
        print("Usage: mano-cua local {start|status|stop}")
        return 1

    if args.command == "config":
        return cmd_config(args)

    if args.command == "check":
        return cmd_check(args)

    if args.command == "install-sdk":
        return cmd_install_sdk(args)

    if args.command == "install-model":
        return cmd_install_model(args)

    if args.command == "run":
        if not args.task:
            print("Error: task is required for 'run' command")
            return 1
        if args.local_service_host and not args.local:
            print("Error: --local-service-host can only be used with --local.")
            return 1
        if args.local_service_token and not args.local_service_host:
            print("Error: --local-service-token requires --local-service-host.")
            return 1
        return run_task(
            args.task,
            expected_result=args.expected_result,
            minimize=args.minimize,
            max_steps=args.max_steps,
            local=args.local,
            model_path=args.model_path,
            local_service_host=args.local_service_host,
            local_service_port=args.local_service_port,
            local_service_token=args.local_service_token,
            url=args.url,
            screenshot_cache_dir=args.screenshot_cache_dir,
            app=args.app,
        )

    return 1


if __name__ == "__main__":
    sys.exit(main())
