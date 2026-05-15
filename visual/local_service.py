import json
import logging
import os
import queue
import secrets
import socket
import stat
import threading
import time
import uuid
from concurrent.futures import Future
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

LOCAL_SERVICE_HOST = "127.0.0.1"
LOCAL_SERVICE_DEFAULT_PORT = 53111
LOCAL_SERVICE_TOKEN_HEADER = "X-Mano-Local-Token"
LOCAL_SERVICE_DIR = Path(os.path.expanduser("~/.mano"))
LOCAL_SERVICE_STATE_FILE = LOCAL_SERVICE_DIR / "local-service.json"
LOCAL_SERVICE_LOG_FILE = LOCAL_SERVICE_DIR / "local-service.log"


class LocalServiceError(RuntimeError):
    """Raised when the local service is unavailable or misconfigured."""


def _ensure_service_dir() -> Path:
    LOCAL_SERVICE_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_SERVICE_DIR


def _write_private_json(path: Path, payload: Dict[str, Any]) -> None:
    _ensure_service_dir()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)
    tmp_path.replace(path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def load_local_service_state() -> Optional[Dict[str, Any]]:
    if not LOCAL_SERVICE_STATE_FILE.is_file():
        return None
    try:
        return json.loads(LOCAL_SERVICE_STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_local_service_state(payload: Dict[str, Any]) -> None:
    _write_private_json(LOCAL_SERVICE_STATE_FILE, payload)


def delete_local_service_state() -> None:
    try:
        LOCAL_SERVICE_STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def is_pid_alive(pid: Optional[int]) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def read_local_service_token() -> Optional[str]:
    state = load_local_service_state()
    if not state:
        return None
    return state.get("token")


def make_local_service_headers(token: Optional[str]) -> Dict[str, str]:
    if not token:
        return {}
    return {LOCAL_SERVICE_TOKEN_HEADER: token}


def make_local_service_state(
    host: Optional[str] = None,
    port: Optional[int] = None,
    token: Optional[str] = None,
    *,
    use_connect_host: bool = True,
) -> Dict[str, Any]:
    resolved_host = host or LOCAL_SERVICE_HOST
    connect_host = get_local_service_connect_host(resolved_host) if use_connect_host else resolved_host
    return {
        "host": resolved_host,
        "connect_host": connect_host,
        "port": int(port or LOCAL_SERVICE_DEFAULT_PORT),
        "token": token,
    }


def get_local_service_connect_host(bind_host: Optional[str]) -> str:
    if bind_host in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return bind_host or LOCAL_SERVICE_HOST


def resolve_local_service_endpoint(state: Optional[Dict[str, Any]] = None) -> Tuple[str, int]:
    payload = state or load_local_service_state() or {}
    host = payload.get("connect_host") or get_local_service_connect_host(payload.get("host"))
    port = int(payload.get("port") or LOCAL_SERVICE_DEFAULT_PORT)
    return host, port


def build_local_service_url(path: str, state: Optional[Dict[str, Any]] = None) -> str:
    host, port = resolve_local_service_endpoint(state)
    normalized = path if path.startswith("/") else f"/{path}"
    return f"http://{host}:{port}{normalized}"


def describe_local_service_invalid_response(response: Any) -> str:
    content_type = response.headers.get("Content-Type", "(missing)")
    body = (getattr(response, "text", "") or "").strip()
    snippet = " ".join(body.split())
    if len(snippet) > 200:
        snippet = snippet[:197] + "..."

    message = (
        f"Local service returned an invalid response (HTTP {response.status_code}, "
        f"Content-Type: {content_type})."
    )
    if snippet:
        message += f" Response starts with: {snippet!r}."
    message += " Make sure the target host/port points to a compatible mano-cua local service."
    return message


def request_local_service(
    method: str,
    url: str,
    *,
    payload: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
):
    return requests.request(
        method=method,
        url=url,
        json=payload or {},
        headers=headers or {},
        timeout=timeout,
        proxies={"http": None, "https": None},
        trust_env=False,
    )


def _normalize_model_path(model_path: str) -> str:
    return os.path.abspath(os.path.expanduser(model_path))


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


@dataclass
class LocalSession:
    session_id: str
    task: str
    expected_result: Optional[str]
    client_pid: Optional[int]
    requested_model_path: str
    stop_requested: bool = False
    closed: bool = False
    created_at: str = ""


class LocalInferenceService:
    """Background service that keeps a local model loaded and serves inference requests."""

    def __init__(self, model_path: str, host: str, port: int, token: str):
        self.host = host
        self.port = port
        self.token = token
        self.model_path = _normalize_model_path(model_path)
        self.agent = None
        self.started_at = _utc_now()
        self._server: Optional[ThreadingHTTPServer] = None
        self._server_thread_id = None
        self._shutdown_requested = threading.Event()
        self._lock = threading.RLock()
        self._active_session: Optional[LocalSession] = None
        self._ready = False
        self._last_cleanup_message: Optional[str] = None
        self._logger = self._configure_logging()
        self._agent_thread: Optional[threading.Thread] = None
        self._agent_ready = threading.Event()
        self._agent_queue: "queue.Queue[Any]" = queue.Queue()
        self._agent_sentinel = object()
        self._agent_startup_error: Optional[Exception] = None

    def _configure_logging(self) -> logging.Logger:
        _ensure_service_dir()
        logger = logging.getLogger("mano.local_service")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        if not any(isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == str(LOCAL_SERVICE_LOG_FILE) for handler in logger.handlers):
            handler = logging.FileHandler(LOCAL_SERVICE_LOG_FILE, encoding="utf-8")
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def preload(self) -> None:
        self._logger.info("Loading local model from %s", self.model_path)
        self._ensure_agent_thread()
        self._logger.info("Local model ready: %s", self.model_path)

    def _agent_thread_main(self) -> None:
        try:
            from visual.agents.local import LocalAgent

            agent = LocalAgent(model_path=self.model_path)
            agent.preload_model()
            self.agent = agent
            self._ready = True
            self._agent_ready.set()
        except Exception as exc:
            self._agent_startup_error = exc
            self._agent_ready.set()
            self._logger.exception("Failed to initialize local inference worker")
            return

        while True:
            item = self._agent_queue.get()
            if item is self._agent_sentinel:
                break

            future, method_name, args, kwargs = item
            try:
                result = getattr(self.agent, method_name)(*args, **kwargs)
            except Exception as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)

    def _ensure_agent_thread(self) -> None:
        if self._agent_thread and self._agent_thread.is_alive():
            self._agent_ready.wait()
        else:
            self._agent_ready.clear()
            self._agent_startup_error = None
            self._agent_thread = threading.Thread(
                target=self._agent_thread_main,
                name="mano-local-agent",
                daemon=True,
            )
            self._agent_thread.start()
            self._agent_ready.wait()

        if self._agent_startup_error:
            raise self._agent_startup_error
        if not self.agent:
            raise LocalServiceError("Local inference worker did not initialize successfully.")

    def _call_agent(self, method_name: str, *args: Any, **kwargs: Any) -> Any:
        self._ensure_agent_thread()
        future: Future = Future()
        self._agent_queue.put((future, method_name, args, kwargs))
        return future.result()

    def _stop_agent_thread(self) -> None:
        if not self._agent_thread:
            return
        self._agent_queue.put(self._agent_sentinel)
        self._agent_thread.join(timeout=2)
        self._agent_thread = None

    def export_state(self) -> Dict[str, Any]:
        with self._lock:
            session = self._active_session
            return {
                "host": self.host,
                "connect_host": get_local_service_connect_host(self.host),
                "port": self.port,
                "pid": os.getpid(),
                "token": self.token,
                "model_path": self.model_path,
                "started_at": self.started_at,
                "running": True,
                "ready": self._ready,
                "active_session": session.session_id if session else None,
                "client_pid": session.client_pid if session else None,
                "status": "busy" if session else "idle",
                "last_cleanup": self._last_cleanup_message,
            }

    def persist_state(self) -> None:
        save_local_service_state(self.export_state())

    def _clear_active_session(self, cleanup_message: Optional[str] = None) -> None:
        if cleanup_message:
            self._last_cleanup_message = cleanup_message
        self._active_session = None
        self.persist_state()

    def cleanup_stale_session_if_needed(self) -> Optional[str]:
        with self._lock:
            session = self._active_session
            if not session:
                return None
            if session.client_pid and not is_pid_alive(session.client_pid):
                message = f"stale session cleaned: {session.session_id}"
                self._logger.warning("%s (client pid=%s)", message, session.client_pid)
                self._clear_active_session(cleanup_message=message)
                return message
            return None

    def create_session(self, task: str, expected_result: Optional[str], client_pid: Optional[int], requested_model_path: str) -> Dict[str, Any]:
        normalized_model_path = _normalize_model_path(requested_model_path)
        with self._lock:
            self.cleanup_stale_session_if_needed()
            if normalized_model_path != self.model_path:
                raise LocalServiceError(
                    f"Local service is running with model '{self.model_path}'. Stop the service and restart with '{normalized_model_path}'."
                )
            if self._active_session:
                raise LocalServiceError("Local service is busy with another active local task.")

            self._call_agent("reset_task_state")
            session = LocalSession(
                session_id=f"local-{uuid.uuid4().hex[:12]}",
                task=task,
                expected_result=expected_result,
                client_pid=client_pid,
                requested_model_path=normalized_model_path,
                created_at=_utc_now(),
            )
            self._active_session = session
            self.persist_state()
            return {
                "session_id": session.session_id,
                "status": "READY",
                "model_path": self.model_path,
            }

    def _require_session(self, session_id: str) -> LocalSession:
        with self._lock:
            self.cleanup_stale_session_if_needed()
            session = self._active_session
            if not session or session.session_id != session_id or session.closed:
                raise LocalServiceError("Local session not found.")
            return session

    def step_session(self, session_id: str, tool_results: Optional[list]) -> Dict[str, Any]:
        session = self._require_session(session_id)
        if session.stop_requested:
            return {
                "reasoning": "",
                "actions": [],
                "status": "STOP",
                "action_desc": "Stop requested",
            }

        reasoning, actions, status, action_desc = self._call_agent(
            "predict",
            task_instruction=session.task,
            tool_results=tool_results,
            expected_result=session.expected_result,
        )

        if session.stop_requested and status == "RUNNING":
            status = "STOP"
            actions = []
            action_desc = "Stop requested"

        return {
            "reasoning": reasoning,
            "actions": actions,
            "status": status,
            "action_desc": action_desc,
        }

    def continue_session(self, session_id: str) -> Dict[str, Any]:
        self._require_session(session_id)
        self._call_agent("agree_to_continue")
        return {"ok": True}

    def stop_session(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        session.stop_requested = True
        return {"ok": True, "status": "STOPPING"}

    def close_session(self, session_id: str) -> Dict[str, Any]:
        session = self._require_session(session_id)
        session.closed = True
        with self._lock:
            self._clear_active_session()
        return {"ok": True}

    def shutdown(self) -> Dict[str, Any]:
        with self._lock:
            self.cleanup_stale_session_if_needed()
            if self._active_session:
                raise LocalServiceError("Local service is busy. Stop the current local task before stopping the service.")
            self._shutdown_requested.set()
            if self._server:
                threading.Thread(target=self._server.shutdown, daemon=True).start()
            return {"ok": True}

    def serve_forever(self) -> None:
        service = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ManoLocalService/1.0"

            def log_message(self, format: str, *args: Any) -> None:
                service._logger.info("%s - %s", self.address_string(), format % args)

            def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_json(self) -> Dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length <= 0:
                    return {}
                raw = self.rfile.read(length)
                if not raw:
                    return {}
                return json.loads(raw.decode("utf-8"))

            def _is_loopback_client(self) -> bool:
                client_host = (self.client_address or ("", 0))[0]
                return client_host in {"127.0.0.1", "::1"}

            def _authorize(self) -> bool:
                if self._is_loopback_client():
                    return True
                token = self.headers.get(LOCAL_SERVICE_TOKEN_HEADER)
                return bool(token) and token == service.token

            def _reject_unauthorized(self) -> None:
                self._send_json(401, {"ok": False, "detail": "Unauthorized"})

            def _handle_error(self, exc: Exception) -> None:
                if isinstance(exc, LocalServiceError):
                    self._send_json(409, {"ok": False, "detail": str(exc)})
                else:
                    service._logger.exception("Unhandled local service error")
                    self._send_json(500, {"ok": False, "detail": str(exc)})

            def do_GET(self) -> None:
                if not self._authorize():
                    self._reject_unauthorized()
                    return
                try:
                    if self.path == "/v1/local/status":
                        cleanup = service.cleanup_stale_session_if_needed()
                        payload = service.export_state()
                        payload["ok"] = True
                        payload["cleanup"] = cleanup
                        self._send_json(200, payload)
                        return
                    self._send_json(404, {"ok": False, "detail": "Not found"})
                except Exception as exc:
                    self._handle_error(exc)

            def do_POST(self) -> None:
                if not self._authorize():
                    self._reject_unauthorized()
                    return
                try:
                    payload = self._read_json()
                    if self.path == "/v1/local/shutdown":
                        self._send_json(200, service.shutdown())
                        return
                    if self.path == "/v1/local/sessions":
                        result = service.create_session(
                            task=payload.get("task") or "",
                            expected_result=payload.get("expected_result"),
                            client_pid=payload.get("client_pid"),
                            requested_model_path=payload.get("requested_model_path") or service.model_path,
                        )
                        self._send_json(200, {"ok": True, **result})
                        return
                    if self.path.endswith("/step"):
                        session_id = self.path.split("/")[-2]
                        result = service.step_session(session_id, payload.get("tool_results") or [])
                        self._send_json(200, {"ok": True, **result})
                        return
                    if self.path.endswith("/continue"):
                        session_id = self.path.split("/")[-2]
                        self._send_json(200, service.continue_session(session_id))
                        return
                    if self.path.endswith("/stop"):
                        session_id = self.path.split("/")[-2]
                        self._send_json(200, service.stop_session(session_id))
                        return
                    if self.path.endswith("/close"):
                        session_id = self.path.split("/")[-2]
                        self._send_json(200, service.close_session(session_id))
                        return
                    self._send_json(404, {"ok": False, "detail": "Not found"})
                except Exception as exc:
                    self._handle_error(exc)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        self._server_thread_id = threading.get_ident()
        self.persist_state()
        try:
            self._server.serve_forever()
        finally:
            delete_local_service_state()
            self._stop_agent_thread()
            if self._server:
                self._server.server_close()


def generate_local_service_token() -> str:
    return secrets.token_hex(24)


def validate_local_service_token(token: str) -> str:
    normalized = (token or "").strip()
    if not normalized:
        raise LocalServiceError("Local service token/passphrase cannot be empty.")
    return normalized


def is_port_listening(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0
