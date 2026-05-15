import os
from typing import Any, Dict, List, Optional, Tuple

import requests

from visual.agents.base import BaseAgent
from visual.local_service import (
    LocalServiceError,
    build_local_service_url,
    load_local_service_state,
    make_local_service_headers,
    make_local_service_state,
)


class LocalServiceAgent(BaseAgent):
    """Agent that delegates local inference to the persistent background service."""

    agent_type = "local"

    def __init__(
        self,
        task_instruction: str,
        expected_result: Optional[str],
        requested_model_path: str,
        service_state: Optional[Dict[str, Any]] = None,
    ):
        self.task_instruction = task_instruction
        self.expected_result = expected_result
        self.requested_model_path = os.path.abspath(os.path.expanduser(requested_model_path))
        self.state = service_state or load_local_service_state()
        if not self.state:
            raise LocalServiceError("Local service is not running. Start it with: mano-cua local start")
        self.state = make_local_service_state(
            host=self.state.get("host"),
            port=self.state.get("port"),
            token=self.state.get("token"),
            use_connect_host=False if service_state else True,
        )

        self._headers = make_local_service_headers(self.state.get("token"))
        self.session_id = None
        self.device_id = None
        self._create_session()

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = build_local_service_url(path, self.state)
        try:
            response = requests.request(
                method=method,
                url=url,
                json=payload or {},
                headers=self._headers,
                timeout=600,
            )
        except requests.RequestException as exc:
            raise LocalServiceError(
                "Local service is unavailable. Check `mano-cua local status` and restart it with `mano-cua local start`."
            ) from exc

        if response.status_code == 401:
            raise LocalServiceError("Local service authentication failed. Restart the service with `mano-cua local stop` then `mano-cua local start`.")

        try:
            data = response.json()
        except ValueError as exc:
            raise LocalServiceError("Local service returned an invalid response.") from exc

        if not response.ok or not data.get("ok", False):
            detail = data.get("detail") or f"Local service request failed: HTTP {response.status_code}"
            raise LocalServiceError(detail)
        return data

    def _create_session(self) -> None:
        data = self._request(
            "POST",
            "/v1/local/sessions",
            {
                "task": self.task_instruction,
                "expected_result": self.expected_result,
                "client_pid": os.getpid(),
                "requested_model_path": self.requested_model_path,
            },
        )
        self.session_id = data.get("session_id")

    def predict(
        self,
        task_instruction: str,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        expected_result: Optional[str] = None,
    ) -> Tuple[str, List[Dict[str, Any]], str, str]:
        data = self._request(
            "POST",
            f"/v1/local/sessions/{self.session_id}/step",
            {"tool_results": tool_results or []},
        )
        return (
            data.get("reasoning", ""),
            data.get("actions", []),
            (data.get("status") or "RUNNING").upper(),
            data.get("action_desc", ""),
        )

    def close(self, skip_eval: bool = False, close_reason: Optional[str] = None) -> Optional[dict]:
        if not self.session_id:
            return None
        try:
            self._request("POST", f"/v1/local/sessions/{self.session_id}/close", {})
        except LocalServiceError as exc:
            print(f"Failed to close local session: {exc}")
        finally:
            self.session_id = None
        return None

    def stop(self) -> None:
        if not self.session_id:
            return
        try:
            self._request("POST", f"/v1/local/sessions/{self.session_id}/stop", {})
        except LocalServiceError as exc:
            print(f"Failed to stop local session: {exc}")

    def agree_to_continue(self) -> None:
        if not self.session_id:
            raise LocalServiceError("Local session not available.")
        self._request("POST", f"/v1/local/sessions/{self.session_id}/continue", {})
