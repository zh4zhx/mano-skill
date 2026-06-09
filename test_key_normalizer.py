import unittest
import importlib.util
from pathlib import Path
import platform
import re
import sys
import types
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import Mock, patch

if "requests" not in sys.modules:
    sys.modules["requests"] = types.SimpleNamespace(
        Session=lambda: None,
        RequestException=Exception,
    )


def _load_module(module_name, relative_path):
    module_path = Path(__file__).resolve().parent / relative_path
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


key_normalizer = _load_module("key_normalizer_under_test", Path("visual/agents/key_normalizer.py"))
normalize_actions = key_normalizer.normalize_actions
local_service_module = _load_module("local_service_under_test", Path("visual/local_service.py"))


def _load_parse_hotkey_spec():
    local_py = (Path(__file__).resolve().parent / "visual" / "agents" / "local.py").read_text(encoding="utf-8")
    start = local_py.index("    def _get_current_stage")
    end = local_py.index("\n    def _parse_action", start)
    method_block = local_py[start:end]
    lines = method_block.splitlines()
    normalized_lines = [lines[0].lstrip()]
    normalized_lines.extend(line[4:] if line.startswith("    ") else line for line in lines[1:])
    class_src = "class _HotkeyParser:\n" + "\n".join(f"    {line}" if line else "" for line in normalized_lines)
    namespace = {"platform": platform, "re": re, "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple}
    exec(class_src, namespace)
    return namespace["_HotkeyParser"]


HotkeyParser = _load_parse_hotkey_spec()


def _load_parse_action_helpers():
    local_py = (Path(__file__).resolve().parent / "visual" / "agents" / "local.py").read_text(encoding="utf-8")
    start = local_py.index("    def _parse_action")
    end = local_py.index("\n    # ─── Action conversion", start)
    method_block = local_py[start:end]
    lines = method_block.splitlines()
    normalized_lines = [lines[0].lstrip()]
    normalized_lines.extend(line[4:] if line.startswith("    ") else line for line in lines[1:])
    class_src = "class _ActionParser:\n" + "\n".join(f"    {line}" if line else "" for line in normalized_lines)
    namespace = {"re": re, "Optional": __import__("typing").Optional}
    exec(class_src, namespace)
    return namespace["_ActionParser"]


ActionParser = _load_parse_action_helpers()


def _load_detokenizer_patch_helpers():
    local_py = (Path(__file__).resolve().parent / "visual" / "agents" / "local.py").read_text(encoding="utf-8")
    if "_MANO_BPE_DETOKENIZER_PATCHED_ATTR" not in local_py:
        def _missing_detokenizer_patch():
            raise unittest.SkipTest("local detokenizer patch helper is not present in this checkout")
        return _missing_detokenizer_patch
    start = local_py.index("_MANO_BPE_DETOKENIZER_PATCHED_ATTR")
    end = local_py.index("\n\nclass LocalAgent", start)
    helpers_block = local_py[start:end]
    namespace = {
        "Dict": __import__("typing").Dict,
        "List": __import__("typing").List,
        "Optional": __import__("typing").Optional,
        "logger": types.SimpleNamespace(debug=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None),
    }
    exec(helpers_block, namespace)
    return namespace["_install_utf8_tolerant_bpe_detokenizer"]


install_utf8_tolerant_bpe_detokenizer = _load_detokenizer_patch_helpers()


def _load_local_service_agent_create_session():
    local_service_agent_py = (Path(__file__).resolve().parent / "visual" / "agents" / "local_service.py").read_text(encoding="utf-8")
    start = local_service_agent_py.index("    def _create_session")
    end = local_service_agent_py.index("\n    def predict", start)
    method_block = local_service_agent_py[start:end]
    lines = method_block.splitlines()
    normalized_lines = [lines[0].lstrip()]
    normalized_lines.extend(line[4:] if line.startswith("    ") else line for line in lines[1:])
    class_src = "class _LocalServiceAgentHarness:\n" + "\n".join(f"    {line}" if line else "" for line in normalized_lines)
    namespace = {"os": __import__("os"), "uuid": __import__("uuid")}
    exec(class_src, namespace)
    return namespace["_LocalServiceAgentHarness"]


LocalServiceAgentHarness = _load_local_service_agent_create_session()


def _load_build_initial_tool_results():
    task_model_py = (Path(__file__).resolve().parent / "visual" / "model" / "task_model.py").read_text(encoding="utf-8")
    start = task_model_py.index("    def _build_initial_tool_results")
    end = task_model_py.index("\n    def _capture_task_end_screenshot", start)
    method_block = task_model_py[start:end]
    lines = method_block.splitlines()
    normalized_lines = [lines[0].lstrip()]
    normalized_lines.extend(line[4:] if line.startswith("    ") else line for line in lines[1:])
    class_src = "class _TaskModelHarness:\n" + "\n".join(f"    {line}" if line else "" for line in normalized_lines)
    namespace = {
        "List": __import__("typing").List,
        "Dict": __import__("typing").Dict,
        "Any": __import__("typing").Any,
        "make_tool_result": lambda **kwargs: kwargs,
    }
    exec(class_src, namespace)
    return namespace["_TaskModelHarness"]


TaskModelHarness = _load_build_initial_tool_results()


def _load_minimize_method():
    view_py = (Path(__file__).resolve().parent / "visual" / "view" / "task_overlay_view.py").read_text(encoding="utf-8")
    start = view_py.index("    def minimize_and_restore_focus")
    end = view_py.index("\n    def _setup_dragging", start)
    method_block = view_py[start:end]
    lines = method_block.splitlines()
    normalized_lines = [lines[0].lstrip()]
    normalized_lines.extend(line[4:] if line.startswith("    ") else line for line in lines[1:])
    class_src = "class _OverlayHarness:\n" + "\n".join(f"    {line}" if line else "" for line in normalized_lines)
    namespace = {}
    exec(class_src, namespace)
    return namespace["_OverlayHarness"]


OverlayHarness = _load_minimize_method()


def _load_authorize_helpers():
    local_service_py = (Path(__file__).resolve().parent / "visual" / "local_service.py").read_text(encoding="utf-8")
    start = local_service_py.index("            def _is_loopback_client")
    end = local_service_py.index("\n            def _reject_unauthorized", start)
    method_block = local_service_py[start:end]
    lines = method_block.splitlines()
    normalized_lines = [line[12:] if line.startswith("            ") else line for line in lines]
    class_src = "class _HandlerHarness:\n" + "\n".join(f"    {line}" if line else "" for line in normalized_lines)
    namespace = {
        "LOCAL_SERVICE_TOKEN_HEADER": "X-Mano-Local-Token",
        "service": type("Service", (), {"token": "secret"})(),
    }
    exec(class_src, namespace)
    return namespace["_HandlerHarness"], namespace


AuthorizeHarness, authorize_globals = _load_authorize_helpers()


def _load_local_service_helpers():
    local_service_py = (Path(__file__).resolve().parent / "visual" / "local_service.py").read_text(encoding="utf-8")
    start = local_service_py.index("def make_local_service_state")
    describe_start = local_service_py.index("\n\ndef describe_local_service_invalid_response", start)
    middle = local_service_py.index("\n\ndef _normalize_model_path", describe_start)
    token_start = local_service_py.index("def validate_local_service_token")
    token_end = local_service_py.index("\n\ndef is_port_listening", token_start)
    helpers_block = local_service_py[start:middle] + "\n\n" + local_service_py[token_start:token_end]
    namespace = {
        "Any": __import__("typing").Any,
        "Dict": __import__("typing").Dict,
        "Optional": __import__("typing").Optional,
        "Tuple": __import__("typing").Tuple,
        "LocalServiceError": type("LocalServiceError", (RuntimeError,), {}),
        "LOCAL_SERVICE_DEFAULT_PORT": 53111,
        "LOCAL_SERVICE_HOST": "127.0.0.1",
        "load_local_service_state": lambda: None,
        "requests": types.SimpleNamespace(request=lambda **kwargs: kwargs),
    }
    exec(helpers_block, namespace)
    return (
        namespace["make_local_service_state"],
        namespace["get_local_service_connect_host"],
        namespace["resolve_local_service_endpoint"],
        namespace["describe_local_service_invalid_response"],
        namespace["describe_local_service_unavailable"],
        namespace["request_local_service"],
        namespace["validate_local_service_token"],
        namespace["LocalServiceError"],
    )


(
    make_local_service_state,
    get_local_service_connect_host,
    resolve_local_service_endpoint,
    describe_local_service_invalid_response,
    describe_local_service_unavailable,
    request_local_service,
    validate_local_service_token,
    LocalServiceError,
) = _load_local_service_helpers()


def _load_prepare_local_service_run():
    vla_py = (Path(__file__).resolve().parent / "visual" / "vla.py").read_text(encoding="utf-8")
    start = vla_py.index("def _prepare_local_service_run")
    end = vla_py.index("\n\ndef run_task", start)
    helpers_block = vla_py[start:end]
    namespace = {
        "LOCAL_SERVICE_DEFAULT_PORT": 53111,
        "LocalServiceError": type("LocalServiceError", (RuntimeError,), {}),
        "make_local_service_state": lambda **kwargs: kwargs,
        "ensure_local_service_ready": lambda **kwargs: kwargs,
        "_resolve_local_model_path": lambda model_path=None: model_path,
    }
    exec(helpers_block, namespace)
    return namespace["_prepare_local_service_run"], namespace["LocalServiceError"]


prepare_local_service_run, PrepareLocalServiceError = _load_prepare_local_service_run()


def _load_running_local_service_state_helper():
    vla_py = (Path(__file__).resolve().parent / "visual" / "vla.py").read_text(encoding="utf-8")
    start = vla_py.index("def _load_running_local_service_state")
    end = vla_py.index("\n\ndef _local_service_request", start)
    helper_block = vla_py[start:end]
    namespace = {
        "load_local_service_state": lambda: None,
        "LocalServiceError": type("LocalServiceError", (RuntimeError,), {}),
        "LOCAL_SERVICE_DEFAULT_PORT": 53111,
        "get_local_service_connect_host": lambda host: host or "127.0.0.1",
        "is_pid_alive": lambda pid: False,
        "is_port_listening": lambda host, port: False,
        "delete_local_service_state": lambda: None,
    }
    exec(helper_block, namespace)
    return namespace["_load_running_local_service_state"], namespace["LocalServiceError"]


load_running_local_service_state_helper, LoadRunningLocalServiceError = _load_running_local_service_state_helper()


def _load_ensure_local_service_ready_helper():
    vla_py = (Path(__file__).resolve().parent / "visual" / "vla.py").read_text(encoding="utf-8")
    start = vla_py.index("def ensure_local_service_ready")
    end = vla_py.index("\n\ndef _resolve_local_service_python", start)
    helper_block = vla_py[start:end]
    namespace = {
        "os": __import__("os"),
        "LOCAL_SERVICE_DEFAULT_PORT": 53111,
        "LocalServiceError": type("LocalServiceError", (RuntimeError,), {}),
        "_load_running_local_service_state": lambda service_state=None: service_state or {},
        "_local_service_request": lambda method, path, payload=None, timeout=30, service_state=None: {},
    }
    exec(helper_block, namespace)
    return namespace["ensure_local_service_ready"], namespace["LocalServiceError"]


ensure_local_service_ready_helper, EnsureLocalServiceReadyError = _load_ensure_local_service_ready_helper()


def _load_stop_session_helper():
    vla_py = (Path(__file__).resolve().parent / "visual" / "vla.py").read_text(encoding="utf-8")
    start = vla_py.index("def stop_session")
    end = vla_py.index("\n\ndef _open_url_in_browser", start)
    helper_block = vla_py[start:end]
    namespace = {
        "LOCAL_SERVICE_DEFAULT_PORT": 53111,
        "LocalServiceError": type("LocalServiceError", (RuntimeError,), {}),
        "make_local_service_state": lambda **kwargs: kwargs,
        "_local_service_request": lambda method, path, payload=None, timeout=30, service_state=None: {},
        "print": lambda *args, **kwargs: None,
    }
    exec(helper_block, namespace)
    return namespace["stop_session"]


stop_session_helper = _load_stop_session_helper()


class KeyNormalizerTests(unittest.TestCase):
    def test_preserve_structured_hotkey_fields(self):
        actions = [{
            "name": "computer",
            "input": {
                "action": "key",
                "modifiers": ["cmd"],
                "mains": ["3"],
            },
            "id": "1",
            "action_type": "tool_use",
        }]

        normalized = normalize_actions(actions)

        self.assertEqual(normalized[0]["input"]["modifiers"], ["cmd"])
        self.assertEqual(normalized[0]["input"]["mains"], ["3"])

    def test_preserve_ctrl_combo_text(self):
        actions = [{
            "name": "computer",
            "input": {
                "action": "key",
                "text": "ctrl+3",
            },
            "id": "2",
            "action_type": "tool_use",
        }]

        normalized = normalize_actions(actions)

        self.assertEqual(normalized[0]["input"]["modifiers"], ["ctrl"])
        self.assertEqual(normalized[0]["input"]["mains"], ["3"])

    def test_preserve_delete_key_in_combo(self):
        actions = [{
            "name": "computer",
            "input": {
                "action": "key",
                "text": "ctrl+delete",
            },
            "id": "3",
            "action_type": "tool_use",
        }]

        normalized = normalize_actions(actions)

        self.assertEqual(normalized[0]["input"]["modifiers"], ["ctrl"])
        self.assertEqual(normalized[0]["input"]["mains"], ["delete"])

    def test_normalize_common_command_typo_on_macos(self):
        actions = [{
            "name": "computer",
            "input": {
                "action": "key",
                "text": "commad+f",
            },
            "id": "4",
            "action_type": "tool_use",
        }]

        with patch.object(key_normalizer.platform, "system", return_value="Darwin"):
            normalized = normalize_actions(actions)

        self.assertEqual(normalized[0]["input"]["modifiers"], ["cmd"])
        self.assertEqual(normalized[0]["input"]["mains"], ["f"])


class LocalAgentHotkeyParseTests(unittest.TestCase):
    def test_parse_hotkey_does_not_rewrite_ctrl_when_task_mentions_cmd(self):
        agent = HotkeyParser()
        agent._current_task_instruction = "先按 cmd+1，再按 ctrl+tab"

        modifiers, mains = agent._parse_hotkey_spec("ctrl+tab")

        self.assertEqual(modifiers, ["ctrl"])
        self.assertEqual(mains, ["tab"])

    def test_parse_common_command_typo_as_cmd(self):
        agent = HotkeyParser()

        modifiers, mains = agent._parse_hotkey_spec("commad+f")

        self.assertEqual(modifiers, ["cmd"])
        self.assertEqual(mains, ["f"])

    def test_repair_model_ctrl_when_task_explicitly_requests_command_on_macos(self):
        agent = HotkeyParser()
        agent._current_task_instruction = "键盘输入command+f搜索推荐颜色"
        agent._current_expected_result = None
        agent._stage_plan = [{"text": "键盘输入command+f搜索推荐颜色", "hint": "hotkey"}]
        agent._current_stage_idx = 0

        with patch("platform.system", return_value="Darwin"):
            repaired = agent._repair_hotkey_key_for_task("ctrl f")

        self.assertEqual(repaired, "cmd+f")

    def test_do_not_repair_explicit_ctrl_task_on_macos(self):
        agent = HotkeyParser()
        agent._current_task_instruction = "键盘输入ctrl+f搜索推荐颜色"
        agent._current_expected_result = None
        agent._stage_plan = [{"text": "键盘输入ctrl+f搜索推荐颜色", "hint": "hotkey"}]
        agent._current_stage_idx = 0

        with patch("platform.system", return_value="Darwin"):
            repaired = agent._repair_hotkey_key_for_task("ctrl f")

        self.assertEqual(repaired, "ctrl f")


class LocalAgentActionParseTests(unittest.TestCase):
    def test_parse_fallback_scroll_action(self):
        agent = ActionParser()

        parsed = agent._parse_action("scroll;dir=down;amount=3")

        self.assertEqual(parsed, {"action": "scroll", "direction": "down", "amount": 3})


class LocalAgentDetokenizerPatchTests(unittest.TestCase):
    def test_bpe_detokenizer_replaces_invalid_utf8_bytes(self):
        class FakeBPEStreamingDetokenizer:
            _byte_decoder = {"x": 0x85, " ": 32}

            def __init__(self):
                self.tokenmap = ["x", " "]
                self._unflushed = "x"
                self.text = ""
                self.trim_space = False

            def add_token(self, token, skip_special_token_ids=[]):
                v = self.tokenmap[token]
                if self._byte_decoder[v[0]] == 32:
                    self.text += bytearray(self._byte_decoder[c] for c in self._unflushed).decode("utf-8")
                    self._unflushed = v
                else:
                    self._unflushed += v

        fake_tokenizer_utils = types.SimpleNamespace(BPEStreamingDetokenizer=FakeBPEStreamingDetokenizer)
        fake_mlx_vlm = types.SimpleNamespace(tokenizer_utils=fake_tokenizer_utils)
        original_mlx_vlm = sys.modules.get("mlx_vlm")
        original_tokenizer_utils = sys.modules.get("mlx_vlm.tokenizer_utils")
        sys.modules["mlx_vlm"] = fake_mlx_vlm
        sys.modules["mlx_vlm.tokenizer_utils"] = fake_tokenizer_utils
        try:
            install_utf8_tolerant_bpe_detokenizer()
            detokenizer = FakeBPEStreamingDetokenizer()

            detokenizer.add_token(1)

            self.assertEqual(detokenizer.text, "\ufffd")
            self.assertEqual(detokenizer._unflushed, " ")
        finally:
            if original_mlx_vlm is None:
                sys.modules.pop("mlx_vlm", None)
            else:
                sys.modules["mlx_vlm"] = original_mlx_vlm
            if original_tokenizer_utils is None:
                sys.modules.pop("mlx_vlm.tokenizer_utils", None)
            else:
                sys.modules["mlx_vlm.tokenizer_utils"] = original_tokenizer_utils


class LocalServiceAgentSessionTests(unittest.TestCase):
    def test_remote_service_session_does_not_send_client_pid(self):
        agent = LocalServiceAgentHarness()
        agent.task_instruction = "task"
        agent.expected_result = "done"
        agent.requested_model_path = None
        agent.state = {"_remote_service": True}
        agent.uses_remote_service = True
        captured = {}

        def fake_request(method, path, payload):
            captured["method"] = method
            captured["path"] = path
            captured["payload"] = payload
            return {"session_id": "local-123"}

        agent._request = fake_request

        agent._create_session()

        self.assertEqual(agent.session_id, "local-123")
        self.assertNotIn("client_pid", captured["payload"])

    def test_local_service_session_still_sends_client_pid(self):
        agent = LocalServiceAgentHarness()
        agent.task_instruction = "task"
        agent.expected_result = "done"
        agent.requested_model_path = None
        agent.state = {}
        agent.uses_remote_service = False
        captured = {}

        def fake_request(method, path, payload):
            captured["payload"] = payload
            return {"session_id": "local-456"}

        agent._request = fake_request

        agent._create_session()

        self.assertIn("client_pid", captured["payload"])


class TaskModelInitialScreenshotTests(unittest.TestCase):
    def test_remote_service_run_sends_initial_local_screenshot(self):
        model = TaskModelHarness()
        model._task_start_screenshot_bytes = b"png-bytes"
        model.agent = types.SimpleNamespace(uses_remote_service=True)

        results = model._build_initial_tool_results()

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["tool_use_id"], "initial-screenshot")
        self.assertEqual(results[0]["message"], "initial screenshot captured")
        self.assertEqual(results[0]["screenshot_bytes"], b"png-bytes")

    def test_non_remote_run_does_not_send_initial_screenshot_tool_result(self):
        model = TaskModelHarness()
        model._task_start_screenshot_bytes = b"png-bytes"
        model.agent = types.SimpleNamespace(uses_remote_service=False)

        results = model._build_initial_tool_results()

        self.assertEqual(results, [])


class OverlayMinimizeTests(unittest.TestCase):
    def test_minimize_and_restore_focus_restores_previous_app(self):
        view = OverlayHarness()
        view._ui_initialized = True
        view.root = object()
        view._minimized = False
        view._toggle_minimize = Mock()
        view._previous_app = Mock()

        view.minimize_and_restore_focus()

        view._toggle_minimize.assert_called_once_with()
        view._previous_app.activateWithOptions_.assert_called_once_with(0)


class LocalServiceEndpointTests(unittest.TestCase):
    def test_connect_host_falls_back_to_loopback_for_wildcard_bind(self):
        self.assertEqual(get_local_service_connect_host("0.0.0.0"), "127.0.0.1")
        self.assertEqual(get_local_service_connect_host("::"), "127.0.0.1")

    def test_resolve_endpoint_prefers_stored_connect_host(self):
        host, port = resolve_local_service_endpoint({"host": "0.0.0.0", "connect_host": "127.0.0.1", "port": 53112})

        self.assertEqual(host, "127.0.0.1")
        self.assertEqual(port, 53112)

    def test_make_local_service_state_keeps_remote_host_when_requested(self):
        state = make_local_service_state(host="192.168.1.20", port=53111, token="abc", use_connect_host=False)

        self.assertEqual(state["host"], "192.168.1.20")
        self.assertEqual(state["connect_host"], "192.168.1.20")
        self.assertEqual(state["token"], "abc")

    def test_validate_local_service_token_rejects_blank_values(self):
        with self.assertRaises(LocalServiceError):
            validate_local_service_token("   ")

    def test_validate_local_service_token_accepts_passphrase(self):
        self.assertEqual(validate_local_service_token("my-passphrase"), "my-passphrase")


class LocalServiceAuthorizeTests(unittest.TestCase):
    def test_loopback_client_is_authorized_without_token(self):
        handler = AuthorizeHarness()
        handler.client_address = ("127.0.0.1", 12345)
        handler.headers = {}

        self.assertTrue(handler._is_loopback_client())
        self.assertTrue(handler._authorize())

    def test_non_loopback_client_requires_matching_token(self):
        handler = AuthorizeHarness()
        handler.client_address = ("192.168.1.30", 12345)
        handler.headers = {"X-Mano-Local-Token": "secret"}

        self.assertTrue(handler._authorize())

    def test_non_loopback_client_without_token_is_rejected(self):
        handler = AuthorizeHarness()
        handler.client_address = ("192.168.1.30", 12345)
        handler.headers = {}

        self.assertFalse(handler._authorize())


class LocalServiceRunPreparationTests(unittest.TestCase):
    def test_remote_service_run_does_not_require_local_model_path(self):
        state_calls = []
        ready_calls = []

        def fake_make_local_service_state(**kwargs):
            state_calls.append(kwargs)
            return {"state": "remote", **kwargs}

        def fake_ensure_local_service_ready(**kwargs):
            ready_calls.append(kwargs)
            return {"service": "ready", **kwargs}

        prepare_local_service_run.__globals__["make_local_service_state"] = fake_make_local_service_state
        prepare_local_service_run.__globals__["ensure_local_service_ready"] = fake_ensure_local_service_ready
        prepare_local_service_run.__globals__["_resolve_local_model_path"] = lambda model_path=None: (_ for _ in ()).throw(
            AssertionError("_resolve_local_model_path should not be used for remote service runs")
        )

        service_state, requested_model_path = prepare_local_service_run(
            local_service_host="192.168.1.20",
            local_service_port=53112,
            local_service_token="my-passphrase",
        )

        self.assertEqual(
            state_calls,
            [{
                "host": "192.168.1.20",
                "port": 53112,
                "token": "my-passphrase",
                "use_connect_host": False,
            }],
        )
        self.assertEqual(
            ready_calls,
            [{
                "requested_model_path": None,
                "service_state": {
                    "state": "remote",
                    "host": "192.168.1.20",
                    "port": 53112,
                    "token": "my-passphrase",
                    "use_connect_host": False,
                },
                "require_matching_model_path": False,
            }],
        )
        self.assertEqual(service_state["service"], "ready")
        self.assertIsNone(requested_model_path)

    def test_remote_service_run_requires_token(self):
        with self.assertRaises(PrepareLocalServiceError):
            prepare_local_service_run(local_service_host="192.168.1.20")

    def test_local_service_run_requires_resolved_model_path(self):
        ready_calls = []

        def fake_ensure_local_service_ready(**kwargs):
            ready_calls.append(kwargs)
            return {"service": "ready", **kwargs}

        prepare_local_service_run.__globals__["make_local_service_state"] = lambda **kwargs: kwargs
        prepare_local_service_run.__globals__["ensure_local_service_ready"] = fake_ensure_local_service_ready
        prepare_local_service_run.__globals__["_resolve_local_model_path"] = lambda model_path=None: "/models/mano"

        service_state, requested_model_path = prepare_local_service_run(model_path="/models/mano")

        self.assertEqual(
            ready_calls,
            [{
                "requested_model_path": "/models/mano",
                "require_matching_model_path": True,
            }],
        )
        self.assertEqual(service_state["service"], "ready")
        self.assertEqual(requested_model_path, "/models/mano")


class RunningLocalServiceStateTests(unittest.TestCase):
    def test_remote_service_state_skips_local_pid_checks(self):
        port_calls = []

        def fake_is_port_listening(host, port):
            port_calls.append((host, port))
            return True

        load_running_local_service_state_helper.__globals__["is_port_listening"] = fake_is_port_listening
        load_running_local_service_state_helper.__globals__["is_pid_alive"] = lambda pid: (_ for _ in ()).throw(
            AssertionError("is_pid_alive should not run for explicit remote service targets")
        )
        load_running_local_service_state_helper.__globals__["delete_local_service_state"] = lambda: (_ for _ in ()).throw(
            AssertionError("delete_local_service_state should not run for explicit remote service targets")
        )
        load_running_local_service_state_helper.__globals__["get_local_service_connect_host"] = lambda host: host

        state = load_running_local_service_state_helper(
            {"host": "192.168.1.20", "connect_host": "192.168.1.20", "port": 53111, "token": "abc"}
        )

        self.assertEqual(port_calls, [("192.168.1.20", 53111)])
        self.assertEqual(state["host"], "192.168.1.20")

    def test_remote_service_state_reports_reachability_error(self):
        load_running_local_service_state_helper.__globals__["is_port_listening"] = lambda host, port: False
        load_running_local_service_state_helper.__globals__["get_local_service_connect_host"] = lambda host: host

        with self.assertRaises(LoadRunningLocalServiceError) as ctx:
            load_running_local_service_state_helper(
                {"host": "192.168.1.20", "connect_host": "192.168.1.20", "port": 53111, "token": "abc"}
            )

        self.assertIn("192.168.1.20:53111", str(ctx.exception))


class EnsureLocalServiceReadyTests(unittest.TestCase):
    def test_remote_service_keeps_caller_endpoint_after_status_merge(self):
        ensure_local_service_ready_helper.__globals__["_load_running_local_service_state"] = (
            lambda service_state=None: dict(service_state or {})
        )
        ensure_local_service_ready_helper.__globals__["_local_service_request"] = (
            lambda method, path, payload=None, timeout=30, service_state=None: {
                "ok": True,
                "ready": True,
                "host": "0.0.0.0",
                "connect_host": "127.0.0.1",
                "port": 53111,
                "token": "remote-token",
            }
        )

        merged = ensure_local_service_ready_helper(
            requested_model_path=None,
            service_state={
                "host": "192.168.1.20",
                "connect_host": "192.168.1.20",
                "port": 53111,
                "token": "my-passphrase",
            },
            require_matching_model_path=False,
        )

        self.assertEqual(merged["host"], "192.168.1.20")
        self.assertEqual(merged["connect_host"], "192.168.1.20")
        self.assertEqual(merged["port"], 53111)
        self.assertEqual(merged["token"], "my-passphrase")


class StopSessionTests(unittest.TestCase):
    def test_remote_local_stop_closes_all_active_remote_sessions(self):
        calls = []

        def fake_local_service_request(method, path, payload=None, timeout=30, service_state=None):
            calls.append((method, path, payload, service_state))
            if path == "/v1/local/status":
                return {
                    "sessions": [
                        {"session_id": "local-abc123"},
                        {"session_id": "local-def456"},
                    ]
                }
            return {"ok": True}

        stop_session_helper.__globals__["make_local_service_state"] = lambda **kwargs: kwargs
        stop_session_helper.__globals__["_local_service_request"] = fake_local_service_request

        result = stop_session_helper(
            local=True,
            local_service_host="192.168.1.20",
            local_service_port=53111,
            local_service_token="test1024",
        )

        self.assertEqual(result, 0)
        self.assertEqual(calls[0][1], "/v1/local/status")
        self.assertEqual(calls[1][1], "/v1/local/sessions/local-abc123/stop")
        self.assertEqual(calls[2][1], "/v1/local/sessions/local-abc123/close")
        self.assertEqual(calls[3][1], "/v1/local/sessions/local-def456/stop")
        self.assertEqual(calls[4][1], "/v1/local/sessions/local-def456/close")

    def test_remote_local_stop_can_target_one_session(self):
        calls = []

        def fake_local_service_request(method, path, payload=None, timeout=30, service_state=None):
            calls.append((method, path, payload, service_state))
            if path == "/v1/local/status":
                return {"sessions": [{"session_id": "local-abc123"}, {"session_id": "local-def456"}]}
            return {"ok": True}

        stop_session_helper.__globals__["make_local_service_state"] = lambda **kwargs: kwargs
        stop_session_helper.__globals__["_local_service_request"] = fake_local_service_request

        result = stop_session_helper(
            local=True,
            local_service_host="192.168.1.20",
            local_service_port=53111,
            local_service_token="test1024",
            session_id="local-def456",
        )

        self.assertEqual(result, 0)
        self.assertEqual([call[1] for call in calls], [
            "/v1/local/status",
            "/v1/local/sessions/local-def456/stop",
            "/v1/local/sessions/local-def456/close",
        ])


class FakeLocalRuntime:
    load_count = 0

    def __init__(self, model_path):
        self.model_path = model_path
        self.model_name = "fake-model"
        self.loaded = False

    def ensure_loaded(self):
        if not self.loaded:
            FakeLocalRuntime.load_count += 1
            self.loaded = True


class FakeLocalAgent:
    calls = {}

    def __init__(self, model_path=None, *, runtime=None, session_id=None):
        self.runtime = runtime
        self.session_id = session_id
        self.prompt_history = []
        self.step_count = 0

    def predict(self, task_instruction, tool_results=None, expected_result=None):
        self.step_count += 1
        self.prompt_history.append({
            "desc": task_instruction,
            "action": {"action": "wait"},
            "actions": [{"action": "wait"}],
            "screenshot_b64": "shot",
        })
        if len(self.prompt_history) > 4:
            self.prompt_history = self.prompt_history[-4:]
        FakeLocalAgent.calls[self.session_id] = FakeLocalAgent.calls.get(self.session_id, 0) + 1
        status = "DONE" if task_instruction == "done task" else "RUNNING"
        return "reason", [{"id": f"{self.session_id}-{self.step_count}", "action_type": "WAIT"}], status, f"{task_instruction}:{self.step_count}"

    def agree_to_continue(self):
        self.prompt_history.append({"desc": "continue", "action": {"action": "continue"}, "screenshot_b64": ""})


class LocalInferenceServiceMultiSessionTests(unittest.TestCase):
    def setUp(self):
        FakeLocalRuntime.load_count = 0
        FakeLocalAgent.calls = {}
        self.original_local_agent_module = sys.modules.get("visual.agents.local")
        sys.modules["visual.agents.local"] = types.SimpleNamespace(
            LocalModelRuntime=FakeLocalRuntime,
            LocalAgent=FakeLocalAgent,
        )

        self.saved_state_writer = local_service_module.save_local_service_state
        local_service_module.save_local_service_state = lambda payload: None
        self.service = local_service_module.LocalInferenceService(
            model_path="/models/mano",
            host="127.0.0.1",
            port=53111,
            token="token",
        )
        self.service.preload()

    def tearDown(self):
        if self.original_local_agent_module is None:
            sys.modules.pop("visual.agents.local", None)
        else:
            sys.modules["visual.agents.local"] = self.original_local_agent_module
        local_service_module.save_local_service_state = self.saved_state_writer

    def test_creates_multiple_sessions_with_one_loaded_runtime(self):
        first = self.service.create_session("task one", None, None, "/models/mano")
        second = self.service.create_session("task two", None, None, "/models/mano")

        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertEqual(FakeLocalRuntime.load_count, 1)
        self.assertEqual(len(self.service.export_state()["sessions"]), 2)

    def test_session_contexts_do_not_pollute_each_other(self):
        first = self.service.create_session("task one", None, None, "/models/mano")["session_id"]
        second = self.service.create_session("task two", None, None, "/models/mano")["session_id"]

        self.service.step_session(first, [], request_id="a1")
        self.service.step_session(second, [], request_id="b1")
        self.service.step_session(first, [], request_id="a2")

        first_agent = self.service._sessions[first].agent
        second_agent = self.service._sessions[second].agent
        self.assertEqual(first_agent.step_count, 2)
        self.assertEqual(second_agent.step_count, 1)
        self.assertEqual([entry["desc"] for entry in first_agent.prompt_history], ["task one", "task one"])
        self.assertEqual([entry["desc"] for entry in second_agent.prompt_history], ["task two"])

    def test_idempotent_step_reuses_cached_result_and_detects_payload_mismatch(self):
        session_id = self.service.create_session("task one", None, None, "/models/mano")["session_id"]

        first = self.service.step_session(session_id, [{"tool_use_id": "1"}], request_id="same")
        second = self.service.step_session(session_id, [{"tool_use_id": "1"}], request_id="same")

        self.assertEqual(first, second)
        self.assertEqual(FakeLocalAgent.calls[session_id], 1)
        with self.assertRaises(local_service_module.LocalServiceConflictError):
            self.service.step_session(session_id, [{"tool_use_id": "2"}], request_id="same")

    def test_idempotency_cache_keeps_recent_16(self):
        session_id = self.service.create_session("task one", None, None, "/models/mano")["session_id"]

        for idx in range(17):
            self.service.step_session(session_id, [{"tool_use_id": str(idx)}], request_id=f"req-{idx}")

        cache = self.service._sessions[session_id].idempotency_cache
        self.assertEqual(len(cache), 16)
        self.assertNotIn("req-0", cache)
        self.assertIn("req-16", cache)

    def test_terminal_step_auto_closes_and_close_is_idempotent(self):
        session_id = self.service.create_session("done task", None, None, "/models/mano")["session_id"]

        result = self.service.step_session(session_id, [], request_id="done")

        self.assertEqual(result["status"], "DONE")
        self.assertNotIn(session_id, self.service._sessions)
        self.assertEqual(self.service.step_session(session_id, [], request_id="done"), result)
        self.assertEqual(self.service.close_session(session_id), {"ok": True, "closed": True})

    def test_stop_marks_session_and_next_step_returns_stop(self):
        session_id = self.service.create_session("task one", None, None, "/models/mano")["session_id"]

        self.service.stop_session(session_id)
        result = self.service.step_session(session_id, [], request_id="stop-step")

        self.assertEqual(result["status"], "STOP")
        self.assertEqual(FakeLocalAgent.calls.get(session_id, 0), 0)
        self.assertNotIn(session_id, self.service._sessions)

    def test_close_releases_one_session_without_closing_other(self):
        first = self.service.create_session("task one", None, None, "/models/mano")["session_id"]
        second = self.service.create_session("task two", None, None, "/models/mano")["session_id"]

        self.service.close_session(first)
        self.service.step_session(second, [], request_id="b1")

        self.assertNotIn(first, self.service._sessions)
        self.assertIn(second, self.service._sessions)


class LocalServiceResponseDiagnosticsTests(unittest.TestCase):
    def test_invalid_response_message_includes_status_content_type_and_body_snippet(self):
        response = types.SimpleNamespace(
            status_code=404,
            headers={"Content-Type": "text/html"},
            text="<html><title>Not Found</title><body>missing</body></html>",
        )

        message = describe_local_service_invalid_response(response)

        self.assertIn("HTTP 404", message)
        self.assertIn("Content-Type: text/html", message)
        self.assertIn("Not Found", message)
        self.assertIn("compatible mano-cua local service", message)

    def test_remote_unavailable_message_mentions_lan_exposure_and_firewall(self):
        message = describe_local_service_unavailable("192.168.1.20", 53111, remote=True)

        self.assertIn("192.168.1.20:53111", message)
        self.assertIn("--host 0.0.0.0", message)
        self.assertIn("firewall", message)

    def test_local_service_requests_disable_environment_proxies(self):
        captured = {}

        class FakeSession:
            def __init__(self):
                self.trust_env = True

            def request(self, **kwargs):
                captured.update(kwargs)
                captured["trust_env"] = self.trust_env
                return kwargs

            def close(self):
                captured["closed"] = True

        request_local_service.__globals__["requests"] = types.SimpleNamespace(Session=FakeSession)

        request_local_service(
            "GET",
            "http://192.168.1.20:53111/v1/local/status",
            headers={"X-Test": "1"},
            timeout=5,
        )

        self.assertEqual(captured["proxies"], {"http": None, "https": None})
        self.assertFalse(captured["trust_env"])
        self.assertTrue(captured["closed"])


if __name__ == "__main__":
    unittest.main()
