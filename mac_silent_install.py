import argparse
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import psutil
import requests


LOG = logging.getLogger(__name__)


class MacSilentInstaller:
    install_path_cache: Dict[str, str] = {}
    _device_locks: Dict[str, threading.Lock] = {}
    _state_lock = threading.Lock()

    def __init__(self, payload: Dict[str, Any], logger: Optional[logging.Logger] = None):
        self.payload = payload
        self.logger = logger or LOG
        self.force_stop = False
        self.udid = self._extract_udid(payload)

    @classmethod
    def reset_runtime_state(cls) -> None:
        with cls._state_lock:
            cls.install_path_cache.clear()
            cls._device_locks.clear()

    @classmethod
    def _device_lock(cls, udid: str) -> threading.Lock:
        with cls._state_lock:
            return cls._device_locks.setdefault(udid, threading.Lock())

    @staticmethod
    def _extract_udid(payload: Dict[str, Any]) -> str:
        device = payload.get("device")
        if isinstance(device, dict) and device.get("udId"):
            return str(device["udId"])
        return str(payload.get("udId", ""))

    @staticmethod
    def extract_app_name(app_path: str) -> str:
        path = Path(app_path)
        if path.suffix.lower() == ".app":
            return path.stem
        return path.name or app_path

    def request_stop(self) -> None:
        self.force_stop = True

    def _check_stop_requested(self) -> None:
        if self.force_stop:
            raise InterruptedError("installation interrupted by stop flag")

    def handle_silent_install(self) -> Dict[str, Any]:
        executor = None
        download_future = None
        install_future = None
        package_file = None

        try:
            install_package_path = self._read_install_package_path()
            if not install_package_path:
                return self._result("skipped", reason="missing_install_package_path")

            gp = self.payload.get("gp")
            if not isinstance(gp, dict):
                gp = {}
                self.payload["gp"] = gp

            gp["handleSilentInstall"] = install_package_path
            app_path = str(gp.get("appPath") or "").strip() or None
            resolved_app_path = app_path

            cached_path = self.install_path_cache.get(self.udid)
            if install_package_path == cached_path:
                return self._result(
                    "skipped",
                    reason="already_installed",
                    package=install_package_path,
                    udid=self.udid,
                )

            lock = self._device_lock(self.udid)
            with lock:
                cached_path = self.install_path_cache.get(self.udid)
                if install_package_path == cached_path:
                    return self._result(
                        "skipped",
                        reason="already_installed",
                        package=install_package_path,
                        udid=self.udid,
                    )

                if resolved_app_path:
                    app_name = self.extract_app_name(resolved_app_path)
                    self.kill_app_processes(resolved_app_path, app_name)

                executor = ThreadPoolExecutor(max_workers=1)
                download_future = executor.submit(self.download_file, install_package_path)
                package_file = self._wait_for_future(download_future)

                self._check_stop_requested()

                package_suffix = package_file.suffix.lower()
                if package_suffix == ".dmg":
                    install_future = executor.submit(self.install_dmg, package_file, resolved_app_path)
                elif package_suffix == ".pkg":
                    install_future = executor.submit(self.install_pkg, package_file)
                else:
                    return self._result(
                        "skipped",
                        reason="unsupported_package_format",
                        package=str(package_file),
                    )

                install_result = self._wait_for_future(install_future)
                self._check_stop_requested()

                if package_suffix == ".dmg" and install_result is not None:
                    resolved_app_path = str(install_result)
                    gp["appPath"] = resolved_app_path

                if resolved_app_path:
                    app_name = self.extract_app_name(resolved_app_path)
                    self.restart_app_after_install(resolved_app_path, app_name)

                self.install_path_cache[self.udid] = install_package_path
                return self._result(
                    "installed",
                    package=install_package_path,
                    udid=self.udid,
                    app_path=resolved_app_path,
                )
        except InterruptedError as exc:
            self.request_stop()
            if download_future is not None and not download_future.done():
                download_future.cancel()
            if install_future is not None and not install_future.done():
                install_future.cancel()
            self.logger.info("Silent install interrupted: %s", exc)
            return self._result("interrupted", reason=str(exc), udid=self.udid)
        except Exception as exc:
            self.logger.exception("Failed to install package on device %s", self.udid)
            return self._result("error", reason=str(exc), udid=self.udid)
        finally:
            if package_file is not None:
                self._cleanup_temp_file(package_file)
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)

    def _read_install_package_path(self) -> str:
        return str(self.payload.get("installPackagePath") or "").strip()

    def _wait_for_future(self, future: Future) -> Any:
        while not future.done():
            self._check_stop_requested()
            time.sleep(0.1)
        return future.result()

    def download_file(self, source: str) -> Path:
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            return self._download_remote_file(source)
        if parsed.scheme == "file":
            return self._copy_local_package(Path(parsed.path))
        return self._copy_local_package(Path(source).expanduser())

    def _download_remote_file(self, url: str) -> Path:
        suffix = Path(urlparse(url).path).suffix or ".pkg"
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            try:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    self._check_stop_requested()
                    if chunk:
                        tmp_file.write(chunk)
            finally:
                tmp_file.close()
        return Path(tmp_file.name)

    def _copy_local_package(self, source_path: Path) -> Path:
        if not source_path.exists():
            raise FileNotFoundError(f"install package not found: {source_path}")
        suffix = source_path.suffix or ".pkg"
        tmp_dir = Path(tempfile.mkdtemp(prefix="mac_silent_install_"))
        target_path = tmp_dir / f"package{suffix}"
        shutil.copy2(source_path, target_path)
        return target_path

    def install_dmg(self, dmg_file: Path, app_path: Optional[str]) -> Path:
        mount_point = Path("/Volumes") / f"TempMount_{int(time.time() * 1000)}"
        try:
            self._run_command(
                ["hdiutil", "attach", str(dmg_file), "-mountpoint", str(mount_point), "-nobrowse"]
            )
            app_file = self.find_app_in_directory(mount_point)
            if app_file is None:
                raise FileNotFoundError("no .app bundle found in mounted dmg")

            if app_path is None:
                target_path = Path("/Applications") / app_file.name
            else:
                target_path = Path(app_path)
                if not str(target_path).startswith("/Applications/"):
                    target_path = Path("/Applications") / app_file.name

            self._remove_path(target_path)
            shutil.copytree(app_file, target_path, symlinks=True)
            return target_path
        finally:
            self._run_command(
                ["hdiutil", "detach", str(mount_point), "-force"],
                check=False,
            )

    @staticmethod
    def find_app_in_directory(directory: Path) -> Optional[Path]:
        if not directory.exists() or not directory.is_dir():
            return None
        for child in directory.iterdir():
            if child.suffix.lower() == ".app":
                return child
        return None

    def install_pkg(self, pkg_file: Path) -> None:
        self._run_command(["installer", "-pkg", str(pkg_file), "-target", "/"])

    def kill_app_processes(self, app_path: str, app_name: str) -> None:
        candidates = {app_name.lower()}
        bundle_marker = f"{app_name.lower()}.app"
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                proc_name = str(proc.info.get("name") or "").lower()
                proc_exe = str(proc.info.get("exe") or "").lower()
                proc_cmd = " ".join(proc.info.get("cmdline") or []).lower()
                if proc_exe.startswith(app_path.lower()) or bundle_marker in proc_exe:
                    self._kill_process_tree(proc.pid)
                    continue
                if any(candidate in proc_name or candidate in proc_cmd for candidate in candidates):
                    self._kill_process_tree(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

    def _kill_process_tree(self, pid: int) -> None:
        try:
            process = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return

        try:
            children = process.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            children = []

        for child in children:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return

    def restart_app_after_install(self, app_path: str, app_name: str) -> None:
        try:
            self._run_command(["open", "-a", app_path])
            time.sleep(3)
            self.kill_app_processes(app_path, app_name)
            time.sleep(1)
            self._run_command(["open", "-a", app_path])
            time.sleep(3)
        except Exception:
            self.logger.warning("Failed to restart app after installation: %s", app_path, exc_info=True)

    def _cleanup_temp_file(self, package_file: Path) -> None:
        try:
            if package_file.exists():
                if package_file.is_file():
                    package_file.unlink()
                elif package_file.is_dir():
                    shutil.rmtree(package_file)
            parent = package_file.parent
            if parent.name.startswith("mac_silent_install_") and parent.exists():
                shutil.rmtree(parent, ignore_errors=True)
        except Exception:
            self.logger.warning("Failed to clean temporary package: %s", package_file, exc_info=True)

    def _remove_path(self, path: Path) -> None:
        if not path.exists() and not path.is_symlink():
            return
        if path.is_symlink() or path.is_file():
            path.unlink()
            return
        shutil.rmtree(path)

    def _run_command(self, command: List[str], check: bool = True) -> None:
        self.logger.info("Running command: %s", " ".join(command))
        result = subprocess.run(command, capture_output=not check, text=True)
        if check and result.returncode != 0:
            raise RuntimeError(f"command failed with exit code {result.returncode}: {' '.join(command)}")

    @staticmethod
    def _result(status: str, **extra: Any) -> Dict[str, Any]:
        payload = {"status": status}
        payload.update(extra)
        return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Java handleSilentInstall flow as a pure Python script.")
    parser.add_argument("--payload-json", default="", help="Full task payload as JSON string.")
    parser.add_argument("--payload-file", default="", help="Path to a JSON payload file.")
    parser.add_argument("--install-package-path", default="", help="DMG/PKG path or URL.")
    parser.add_argument("--app-path", default="", help="Target macOS .app bundle path, such as /Applications/Demo.app.")
    parser.add_argument("--udid", default="standalone-mac", help="Device identifier used for install cache isolation.")
    parser.add_argument("--verbose", action="store_true", help="Enable INFO level logging.")
    return parser.parse_args()


def _build_payload_from_direct_args(args: argparse.Namespace) -> Optional[Dict[str, Any]]:
    install_package_path = str(args.install_package_path or "").strip()
    app_path = str(args.app_path or "").strip()
    if not install_package_path:
        return None

    payload = {
        "installPackagePath": install_package_path,
        "udId": str(args.udid or "standalone-mac").strip() or "standalone-mac",
        "gp": {},
    }
    if app_path:
        payload["gp"]["appPath"] = app_path
    return payload


def _load_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.payload_json:
        return json.loads(args.payload_json)
    if args.payload_file:
        return json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    direct_payload = _build_payload_from_direct_args(args)
    if direct_payload is not None:
        return direct_payload
    raise ValueError(
        "provide either --payload-json, --payload-file, or at least --install-package-path "
        "(with optional --app-path/--udid)"
    )


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="[%(levelname)s %(asctime)s %(name)s] %(message)s",
    )
    payload = _load_payload(args)
    result = MacSilentInstaller(payload).handle_silent_install()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] in {"installed", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
