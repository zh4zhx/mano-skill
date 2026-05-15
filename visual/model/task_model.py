import base64
import json
import os
import platform
import threading
import time
import uuid
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from visual.agents.base import BaseAgent

STOP_FLAG_PATH = os.path.expanduser("~/.mano/stop.flag")
from visual.agents.key_normalizer import normalize_actions
from visual.computer.computer_action_executor import ComputerActionExecutor
from visual.config.visual_config import AUTOMATION_CONFIG, TASK_STATUS
from visual.model.task_progress import TaskProgress
from visual.model.task_state import TaskState
from visual.computer.computer_use_util import screenshot_to_bytes, get_or_create_device_id, \
    make_tool_result, current_timestamp_iso, ensure_directory, sanitize_filename_suffix, write_index_json, write_png


class TaskModel:
    """Automation task core model"""

    def __init__(self):
        # State data
        self.state = TaskState()
        self.stop_event = threading.Event()

        self.pause_event = None

        # Callback functions
        self._on_state_changed: Optional[Callable[[TaskState], None]] = None

        # Business components
        self.on_minimize_panel: Optional[Callable] = None
        self.executor: Optional[ComputerActionExecutor] = None
        self.agent: Optional[BaseAgent] = None
        self.expected_result = None
        self.max_steps = None
        self.eval_result = None
        self.screenshot_cache_dir: Optional[str] = None
        self._screenshot_cache_session_dir: Optional[Path] = None
        self._screenshot_cache_entries: List[Dict[str, Any]] = []
        self._screenshot_cache_seq = 0
        self._screenshot_cache_disabled = False
        self._screenshot_cache_session_key: Optional[str] = None

        # Trajectory saving
        self._save_trajectory = False
        self._trajectory_dir = None
        self._session_id = None

    # ========== Data Monitoring ==========
    def set_state_changed_callback(self, callback: Callable[[TaskState], None]):
        """Set state change callback"""
        self._on_state_changed = callback

    def _notify_state_changed(self):
        """Notify state change"""
        if self._on_state_changed:
            self._on_state_changed(self.state)

    # ========== Initialization Methods ==========
    def init_task(
        self,
        task_name: str,
        agent: BaseAgent,
        expected_result: Optional[str] = None,
        max_steps: int = None,
        screenshot_cache_dir: Optional[str] = None,
    ):
        """Initialize automation task"""
        # Basic configuration
        self.state.task_name = task_name
        self.agent = agent
        self.expected_result = expected_result
        self.max_steps = max_steps
        self.state.status = TASK_STATUS["RUNNING"]
        self.state.is_running = True
        self.state.error_msg = None
        self.state.step_idx = 0
        self._reset_screenshot_cache(screenshot_cache_dir)

        # Device and platform information
        self.state.session_id = getattr(agent, "session_id", None)
        self.state.device_id = getattr(agent, "device_id", None) or get_or_create_device_id()
        self.state.platform_tag = platform.system()

        # Trajectory saving
        from visual.config.user_config import get_config
        self._save_trajectory = get_config("save-trajectory") == "true"
        if self._save_trajectory:
            ts = time.strftime("%Y%m%d-%H%M%S")
            self._session_id = f"sess-{ts}-{uuid.uuid4().hex[:8]}"
            self._trajectory_dir = os.path.join(
                os.path.expanduser("~/.mano/trajectory"), self._session_id
            )
            os.makedirs(os.path.join(self._trajectory_dir, "screenshots"), exist_ok=True)
            # Save task metadata
            with open(os.path.join(self._trajectory_dir, "task.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "task": task_name,
                    "expected_result": expected_result,
                    "agent_type": agent.agent_type,
                    "max_steps": max_steps,
                    "session_id": self._session_id,
                    "timestamp": ts,
                }, f, indent=2, ensure_ascii=False)
            print(f"Trajectory: {self._trajectory_dir}")

        # Initialize executor
        self.executor = ComputerActionExecutor(on_minimize_panel=self.on_minimize_panel)

        # Reset stop signal
        self.stop_event.clear()
        try:
            os.remove(STOP_FLAG_PATH)
        except OSError:
            pass

        # Notify state change
        self._notify_state_changed()

    def _reset_screenshot_cache(self, screenshot_cache_dir: Optional[str]):
        """Reset screenshot cache state for a new task run."""
        self.screenshot_cache_dir = screenshot_cache_dir
        self._screenshot_cache_session_dir = None
        self._screenshot_cache_entries = []
        self._screenshot_cache_seq = 0
        self._screenshot_cache_disabled = False
        self._screenshot_cache_session_key = None

    def _disable_screenshot_cache(self, error: Exception):
        """Disable cache writes after a filesystem failure."""
        if not self._screenshot_cache_disabled:
            print(f"Screenshot cache disabled: {error}")
        self._screenshot_cache_disabled = True
        self.screenshot_cache_dir = None
        self._screenshot_cache_session_dir = None

    def _get_screenshot_cache_session_key(self) -> str:
        """Return a stable cache key for the current task run."""
        if self.state.session_id:
            return self.state.session_id
        if self._screenshot_cache_session_key:
            return self._screenshot_cache_session_key
        self._screenshot_cache_session_key = f"local-{uuid.uuid4().hex[:12]}"
        return self._screenshot_cache_session_key

    def _ensure_screenshot_cache_session_dir(self) -> Optional[Path]:
        """Return the cache session directory when caching is enabled."""
        if not self.screenshot_cache_dir or self._screenshot_cache_disabled:
            return None
        if self._screenshot_cache_session_dir:
            return self._screenshot_cache_session_dir

        session_key = self._get_screenshot_cache_session_key()
        try:
            session_dir = ensure_directory(Path(self.screenshot_cache_dir).expanduser() / session_key)
        except Exception as error:
            self._disable_screenshot_cache(error)
            return None

        self._screenshot_cache_session_dir = session_dir
        return session_dir

    def _build_screenshot_cache_filename(
        self,
        seq: int,
        phase: str,
        step_idx: Optional[int] = None,
        action_desc: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str:
        """Build a stable screenshot cache filename."""
        prefix = f"{seq:03d}"
        if phase == "task_start":
            return f"{prefix}_task-start.png"
        if phase == "task_end":
            status_suffix = sanitize_filename_suffix(status, default="unknown")
            return f"{prefix}_task-end_{status_suffix}.png"
        step_value = 0 if step_idx is None else step_idx
        action_suffix = sanitize_filename_suffix(action_desc, default="screenshot")
        return f"{prefix}_step-{step_value:02d}_{action_suffix}.png"

    def _build_screenshot_cache_index(self) -> Dict[str, Any]:
        """Build the screenshot cache index payload."""
        return {
            "session_id": self.state.session_id,
            "task": self.state.task_name,
            "entries": self._screenshot_cache_entries,
        }

    def _record_cached_screenshot(
        self,
        png_bytes: Optional[bytes],
        phase: str,
        step_idx: Optional[int] = None,
        action_desc: Optional[str] = None,
        reasoning: Optional[str] = None,
        status: Optional[str] = None,
    ):
        """Persist a screenshot plus its metadata when caching is enabled."""
        if not png_bytes:
            return

        session_dir = self._ensure_screenshot_cache_session_dir()
        if not session_dir:
            return

        normalized_status = (status or self.state.status or "").lower() or None
        file_name = self._build_screenshot_cache_filename(
            self._screenshot_cache_seq,
            phase=phase,
            step_idx=step_idx,
            action_desc=action_desc,
            status=normalized_status,
        )
        screenshot_path = session_dir / file_name

        entry = {
            "seq": self._screenshot_cache_seq,
            "phase": phase,
            "step_idx": step_idx,
            "status": normalized_status,
            "action_desc": action_desc,
            "reasoning": reasoning,
            "timestamp": current_timestamp_iso(),
            "screenshot_path": file_name,
        }

        try:
            write_png(screenshot_path, png_bytes)
            self._screenshot_cache_entries.append(entry)
            write_index_json(session_dir, self._build_screenshot_cache_index())
            self._screenshot_cache_seq += 1
        except Exception as error:
            self._disable_screenshot_cache(error)

    def _capture_task_start_screenshot(self):
        """Capture and cache the task-start screenshot."""
        if not self.screenshot_cache_dir or self._screenshot_cache_disabled:
            return
        try:
            self._record_cached_screenshot(screenshot_to_bytes(), phase="task_start")
        except Exception as error:
            self._disable_screenshot_cache(error)

    def _capture_task_end_screenshot(self):
        """Capture and cache the task-end screenshot."""
        if not self.screenshot_cache_dir or self._screenshot_cache_disabled:
            return
        try:
            self._record_cached_screenshot(
                screenshot_to_bytes(),
                phase="task_end",
                step_idx=self.state.progress.step_idx,
                action_desc=self.state.progress.action,
                reasoning=self.state.progress.reasoning,
                status=self.state.status,
            )
        except Exception as error:
            self._disable_screenshot_cache(error)

    # ========== Progress Update ==========
    def update_progress(self, step_idx: int, action_desc: str, reasoning: str = "", meta: Dict[str, Any] = None):
        """Update task progress"""
        if not self.state.is_running:
            return

        self.state.progress = TaskProgress(
            step_idx=step_idx,
            action=action_desc,
            reasoning=reasoning,
            action_meta=meta or {}
        )
        print(f"[step {step_idx}] Action: {action_desc}")
        if reasoning:
            print(f"[step {step_idx}] Reasoning: {reasoning}")
        self._notify_state_changed()

    # ========== State Management ==========
    def mark_completed(self):
        """Mark task as completed"""
        self.state.status = TASK_STATUS["COMPLETED"]
        self.state.is_running = False
        self.stop_event.set()
        self._save_final_trajectory()
        self._print_summary("COMPLETED")
        self._notify_state_changed()

    def mark_stopped(self):
        """Mark task as stopped"""
        self.state.status = TASK_STATUS["STOPPED"]
        self.state.is_running = False
        self.stop_event.set()
        # Tell agent to stop (cloud: server API, local: no-op)
        if self.agent:
            self.agent.stop()
        self._save_final_trajectory()
        self._print_summary("STOPPED_BY_USER")
        self._notify_state_changed()

    def mark_error(self, error_msg: str):
        """Mark task as error"""
        self.state.status = TASK_STATUS["ERROR"]
        self.state.error_msg = error_msg
        self.state.is_running = False
        self.stop_event.set()
        self._save_final_trajectory()
        self._print_summary("ERROR", error_msg)
        self._notify_state_changed()

    def _print_summary(self, final_status: str, error_msg: str = ""):
        """Print task summary to stdout for agent consumption"""
        import json
        print(f"\n{'='*50}")
        print(f"Task: {self.state.task_name}")
        print(f"Status: {final_status}")
        print(f"Total steps: {self.state.progress.step_idx}")
        if self.state.progress.action:
            print(f"Last action: {self.state.progress.action}")
        if self.state.progress.reasoning:
            print(f"Last reasoning: {self.state.progress.reasoning}\n")
        if error_msg:
            print(f"Error: {error_msg}")
        if self.eval_result:
            print(f"Evaluation result: {json.dumps(self.eval_result, indent=2, ensure_ascii=False)}")
        print(f"{'='*50}\n")

    def _mark_evaluating(self):
        """Mark task as evaluating - only changes status label, keeps log text"""
        self.state.status = TASK_STATUS["EVALUATING"]
        print("Evaluating task result...")
        self._notify_state_changed()

    def mark_call_user(self):
        """Mark task requires user intervention"""
        self.state.status = TASK_STATUS["CALL_USER"]
        self._notify_state_changed()
        self.pause_task()
        self.pause_event.wait()
        self.state.status = TASK_STATUS["RUNNING"]

    # ========== Current Thread Calls: Control Task Thread ==========

    def stop_task(self):
        """Stop task"""
        if self.state.is_running:
            self.mark_stopped()

    def pause_task(self):
        """Current thread call: pause task (reversible)"""
        if self.state.is_running and not self.stop_event.is_set():
            self.pause_event = threading.Event()
            self.pause_event.clear()  # Set pause signal
            self._notify_state_changed()
            print(f"[Current thread-{threading.current_thread().name}] Send pause signal")

    def resume_task(self):
        """Current thread call: resume task"""
        self.pause_event.set()  # Clear pause signal
        self._notify_state_changed()
        print(f"[Current thread-{threading.current_thread().name}] Send resume signal")

    # ========== Core Business Logic: Run Automation Task ==========
    def run_automation_task(self):
        """Run complete automation task"""
        if not self.state.is_running:
            return

        print(f"Expected result: {self.expected_result}")

        try:
            self._capture_task_start_screenshot()
            self.update_progress(0, "Initializing", "Initializing session connection")

            # Execute task step loop
            self._execute_task_steps()

            # Max steps reached
            if self.state.status == TASK_STATUS["MAX_STEP_REACHED"]:
                self.state.is_running = False
                self.stop_event.set()
                self._save_final_trajectory()
                self._print_summary("MAX_STEP_REACHED")
                self._notify_state_changed()
                skip = not (self.expected_result and self.agent.agent_type == "cloud")
                if not skip:
                    self._mark_evaluating()
                self.eval_result = self.agent.close(skip_eval=skip, close_reason="MAX_STEP_REACHED")
                return

            # Normal completion
            if self.state.is_running and self.state.status != TASK_STATUS["ERROR"]:
                if self.expected_result and self.agent.agent_type == "cloud":
                    self._mark_evaluating()
                    self.eval_result = self.agent.close()
                    self.mark_completed()
                else:
                    self.mark_completed()
                    self.agent.close(skip_eval=True)
                return

        except Exception as e:
            self.mark_error(f"Task execution failed: {str(e)}")
        finally:
            self._capture_task_end_screenshot()
        # Close session for error/stopped/fail cases
        skip = not (self.expected_result and self.agent.agent_type == "cloud")
        self.eval_result = self.agent.close(skip_eval=skip)

    def _execute_task_steps(self):
        """Execute task step loop"""
        tool_results: List[Dict[str, Any]] = []
        step_idx = 0

        while self.state.is_running and not self.stop_event.is_set():
            # 1. Check stop signal (in-process or external file flag)
            if self.stop_event.is_set() or os.path.isfile(STOP_FLAG_PATH):
                print("Stop signal detected. Stopping task...")
                self.mark_stopped()
                break

            # 2. Request next operation via agent
            try:
                reasoning, actions, status, action_desc = self.agent.predict(
                    task_instruction=self.state.task_name,
                    tool_results=tool_results,
                    expected_result=self.expected_result,
                )
            except Exception as e:
                raise RuntimeError(f"Request step failed: {e}")

            # 3. Handle stop status
            if status == "STOP":
                self.mark_stopped()
                break

            # 4. Update UI progress
            if status == "MAX_STEP_REACHED":
                action_desc = "Max steps reached"
            self.update_progress(step_idx, action_desc, reasoning)

            # 5. Handle terminal status
            if status == "DONE":
                break
            elif status == "FAIL":
                self.mark_error("Agent marked task as failed")
                break
            elif status == "MAX_STEP_REACHED":
                self.state.status = TASK_STATUS["MAX_STEP_REACHED"]
                break
            elif status == "CALL_USER":
                self.mark_call_user()
                continue

            # 6. Execute actions (normalize keys for platform before execution)
            tool_results = []
            if not actions:
                continue

            actions = normalize_actions(actions)

            for i, a in enumerate(actions):
                tool_use_id = a.get("id")

                if not tool_use_id:
                    continue

                # Execute single action
                result = self.executor.run_one(a)

                # Delay after action
                time.sleep(AUTOMATION_CONFIG["ACTION_DELAY"])

                # Build tool result
                include_screenshot = (i == len(actions) - 1)
                after_shot = screenshot_to_bytes() if include_screenshot else None
                if include_screenshot:
                    self._record_cached_screenshot(
                        after_shot,
                        phase="step",
                        step_idx=step_idx,
                        action_desc=action_desc,
                        reasoning=reasoning,
                        status=self.state.status,
                    )

                tool_results.append(
                    make_tool_result(
                        tool_use_id=tool_use_id,
                        ok=bool(result["ok"]),
                        message=result["message"],
                        include_screenshot=include_screenshot,
                        screenshot_bytes=after_shot,
                        meta=result.get("meta"),
                    )
                )

            step_idx += 1

            # Save trajectory
            if self._save_trajectory and self._trajectory_dir:
                self._save_step_trajectory(step_idx, reasoning, actions, action_desc, tool_results)

            if self.max_steps is not None and step_idx >= self.max_steps:
                print(f"Max steps ({self.max_steps}) reached, stopping task")
                self.state.status = TASK_STATUS["MAX_STEP_REACHED"]
                break

    # ========== Trajectory Saving ==========
    def _save_step_trajectory(self, step_idx, reasoning, actions, action_desc, tool_results):
        """Save screenshot + action metadata for one step."""
        try:
            for tr in reversed(tool_results or []):
                b64 = tr.get("screenshot_b64")
                if b64:
                    screenshot_bytes = base64.b64decode(b64)
                    path = os.path.join(self._trajectory_dir, "screenshots", f"{step_idx}.png")
                    with open(path, "wb") as f:
                        f.write(screenshot_bytes)
                    break

            step_data = {
                "step": step_idx,
                "reasoning": reasoning,
                "action_desc": action_desc,
                "actions": [{"name": a.get("name"), "input": a.get("input"), "action_type": a.get("action_type")} for a in actions],
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            history_path = os.path.join(self._trajectory_dir, "history.jsonl")
            with open(history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(step_data, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"Warning: failed to save trajectory step {step_idx}: {e}")

    def _save_final_trajectory(self):
        """Save final result summary + final screenshot."""
        if not self._save_trajectory or not self._trajectory_dir:
            return
        try:
            final_shot = screenshot_to_bytes()
            if final_shot:
                path = os.path.join(self._trajectory_dir, "screenshots", "final.png")
                with open(path, "wb") as f:
                    f.write(final_shot)

            result = {
                "task": self.state.task_name,
                "status": self.state.status,
                "total_steps": self.state.progress.step_idx,
                "agent_type": self.agent.agent_type if self.agent else None,
                "session_id": self._session_id,
                "error_msg": self.state.error_msg,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with open(os.path.join(self._trajectory_dir, "result.json"), "w", encoding="utf-8") as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: failed to save final trajectory: {e}")
