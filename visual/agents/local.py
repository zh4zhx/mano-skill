"""LocalAgent — on-device VLM agent using MLX + cider."""

import base64
import io
import logging
import os
import platform
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from visual.agents.base import BaseAgent
from visual.config.visual_config import AUTOMATION_CONFIG

logger = logging.getLogger("mano.local")

LOCAL_AGENT_CONFIG = {
    "MAX_NEW_TOKENS": 2048,
    "TEMPERATURE": 0.0,
    "TOP_P": 1.0,
    "SCREENSHOT_WIDTH": 1920,
    "HISTORY_IMAGE_COUNT": 0,
    "STEP_MEMORY_COUNT": 4,
}


class LocalAgent(BaseAgent):
    """On-device VLM agent using MLX (Qwen3-VL via cider)."""

    agent_type = "local"

    SYSTEM_PROMPT = "You are a helpful assistant."

    INSTRUCTION_TEMPLATE = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
<think>思考过程</think>
<action_desp>动作描述</action_desp>
<action>具体动作</action>

## Action Space

open_app(app_name='') # Open an application by name.
open_url(url='') # Open a URL in the browser.
hover(start_box='<|box_start|>(x1,y1)<|box_end|>')
click(start_box='<|box_start|>(x1,y1)<|box_end|>')
triple_click(start_box='<|box_start|>(x1,y1)<|box_end|>') left click at the coordinate (x1,y1) three times
hotkey_click(start_box='<|box_start|>(x1,y1)<|box_end|>', key=''). press command key and click at the coordinate (x1,y1)
right_single(start_box='<|box_start|>(x1,y1)<|box_end|>').  right click at the coordinate (x1,y1)
type(content='') type the content.
doubleclick(start_box='<|box_start|>(x1,y1)<|box_end|>')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x3,y3)<|box_end|>') # Drag an element from the start coordinate (x1,y1) to the end coordinate (x3,y3).
hotkey(key='') # Trigger a keyboard shortcut.
wait(duration='') # Sleep for specified duration (in seconds) and take a screenshot to check for any changes.
call_user() # Request human assistance
stop(reason='') # If the item can not found in the image, give the reason
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up or right or left', amount='scroll_amount') # Scroll on the specified direction at the coordinate (x1,y1) by the given amount
finish() # The task is completed.

## Note
- Use Chinese in `<think>` part.
- Write a small plan and finally summarize your next action (with its target element) in one sentence in `<action_desp>` part.
- If the user explicitly requests a keyboard shortcut such as command/cmd/ctrl/shift/alt + key, use `hotkey(key='...')` first unless the screenshot clearly shows that the shortcut has already been used or failed.
- For `type(content='...')`, the content must be the exact literal text to input. Preserve Chinese characters, English letters, numbers, spaces, and punctuation exactly as requested. Never transliterate to pinyin, never paraphrase, and never substitute with similar words.
- If an input box already contains unrelated text and the task is to search or replace it, clear the existing text before typing the new content.
- Only choose a search result or feature when the visible text on screen matches the user goal or is an obvious exact follow-up. Do not infer that an unrelated result is correct.
- If a group is already expanded and its child controls are visible, do not click the group header again and collapse it.
- When the task names an exact slider/control label, operate only the row whose visible label exactly matches that name. Do not confuse a parent summary slider with similarly named child sliders.
- Do not output `finish()` unless the exact target control visibly satisfies the requested end state.
- If the current subtask is already satisfied in the screenshot, immediately proceed to the next remaining subtask. Do not wait unless the UI is visibly loading or changing.
- If the current subtask contains an explicit shortcut or explicit literal input text, output that exact shortcut/text literally.

## User Instruction:
{instruction}

"""

    def __init__(self, model_path: str):
        self._model_path = os.path.expanduser(model_path)
        self.model_name = os.path.basename(self._model_path)
        self.cfg = LOCAL_AGENT_CONFIG

        self.model = None
        self.processor = None
        self._custom_generate = None
        self._model_loaded = False
        self._current_task_instruction = ""
        self._current_expected_result = None
        self._planned_task_key = None
        self._stage_plan: List[Dict[str, str]] = []
        self._current_stage_idx = 0
        self._last_processed_tool_result_id = None

        self.prompt_history: list = []
        self.step_count = 0

    def _ensure_model_loaded(self):
        """Lazy-load model on first predict (must be called from worker thread)."""
        if self._model_loaded:
            return
        import mlx_vlm as pm
        from vlm_service import custom_generate

        logger.info(f"Loading local model from {self._model_path} ...")
        self.model, self.processor = pm.load(self._model_path)

        # W8A8 acceleration (config: auto/on/off, default auto)
        from visual.config.user_config import get_config
        w8a8_mode = get_config("w8a8") or "auto"
        if w8a8_mode != "off":
            try:
                import mlx.core as mx
                from cider import convert_model, is_available
                if w8a8_mode == "auto" and not is_available():
                    logger.info("W8A8 not available on this hardware (requires M5+)")
                elif w8a8_mode == "on" or is_available():
                    try:
                        stats = convert_model(self.model.language_model)
                    except Exception:
                        stats = convert_model(self.model)
                    # Pre-warm: quantize all INT8 weights upfront
                    from cider.nn import CiderLinear
                    for module in self.model.language_model.modules():
                        if isinstance(module, CiderLinear):
                            module._ensure_w8()
                    mx.eval(self.model.parameters())
                    logger.info(f"W8A8 enabled: {stats}")
            except ImportError:
                if w8a8_mode == "on":
                    logger.warning("W8A8 requested but cider not installed")
            except Exception as e:
                logger.warning(f"W8A8 init failed: {e}")

        self._custom_generate = custom_generate
        self._model_loaded = True
        logger.info("Local model loaded successfully.")

    def preload_model(self) -> None:
        """Eagerly load the local model for background-service startup."""
        self._ensure_model_loaded()

    def reset_task_state(self) -> None:
        """Reset task-scoped prompt history and planning state for a new session."""
        self._current_task_instruction = ""
        self._current_expected_result = None
        self._planned_task_key = None
        self._stage_plan = []
        self._current_stage_idx = 0
        self._last_processed_tool_result_id = None
        self.prompt_history = []
        self.step_count = 0

    # ─── BaseAgent interface ──────────────────────────────────

    def predict(
        self,
        task_instruction: str,
        tool_results: Optional[List[Dict[str, Any]]] = None,
        expected_result: Optional[str] = None,
    ) -> Tuple[str, List[Dict[str, Any]], str, str]:
        self._ensure_model_loaded()
        _t0 = time.time()
        self._current_task_instruction = task_instruction or ""
        self._current_expected_result = expected_result
        self._ensure_stage_plan()
        self._advance_stage_from_tool_results(tool_results)

        # 1. Extract screenshot
        screenshot_b64 = self._extract_screenshot(tool_results)
        if screenshot_b64 is None:
            screenshot_b64 = self._take_screenshot_b64()

        stage = self._get_current_stage()
        deterministic = self._build_deterministic_stage_action(stage)
        if deterministic:
            think, action_desp, action = deterministic
            parsed_actions = [action]
        else:
            # 2. Build prompt
            user_text, images = self._build_prompt(task_instruction, screenshot_b64)

            # 3. Run inference
            response_text = self._infer(user_text, images)
            print(f"  [model output] {response_text}")

            # 4. Parse response
            self._save_raw_response(response_text)
            parsed = self._parse_response(response_text)
            think = parsed["think"]
            action_desp = parsed["action_desp"]
            parsed_actions = parsed["actions"]

        # 5. Record prompt history
        if screenshot_b64:
            primary_action = parsed_actions[0] if parsed_actions else {}
            self.prompt_history.append({
                "desc": action_desp or str(parsed_actions),
                "action": primary_action,
                "actions": parsed_actions,
                "screenshot_b64": screenshot_b64,
            })

        # 6. Convert to Claude-compatible actions and determine status
        if not parsed_actions:
            actions = [{"action_type": "FAIL"}]
            status = "FAIL"
            action_str = "FAIL"
        else:
            actions = []
            for a in parsed_actions:
                actions.extend(self._convert_action(a))
            status = self._determine_status(actions)
            action_str = " → ".join(self._format_action_desc([a]) for a in actions)

        self.step_count += 1
        elapsed = time.time() - _t0
        print(f"  [step {self.step_count}] {elapsed:.1f}s — {action_str}")

        return think, actions, status, action_str

    def close(self, skip_eval: bool = False, close_reason: Optional[str] = None) -> Optional[dict]:
        # Local mode: no server session to close, no eval
        return None

    def _save_raw_response(self, text: str):
        import json
        log_path = os.path.expanduser("~/.mano/raw_responses.jsonl")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"step": self.step_count, "raw": text}, ensure_ascii=False) + "\n")

    def agree_to_continue(self) -> None:
        self.prompt_history.append({
            "desc": "用户已确认继续",
            "action": {"action": "continue"},
            "screenshot_b64": "",
        })

    def _ensure_stage_plan(self) -> None:
        task_key = (self._current_task_instruction or "", self._current_expected_result or "")
        if task_key == self._planned_task_key:
            return

        self._planned_task_key = task_key
        self._stage_plan = self._build_stage_plan(self._current_task_instruction)
        self._current_stage_idx = 0
        self._last_processed_tool_result_id = None
        self.prompt_history = []
        self.step_count = 0

    def _build_stage_plan(self, task: str) -> List[Dict[str, str]]:
        if not task:
            return []

        normalized = task.strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.replace("，", "\n").replace("。", "\n").replace("；", "\n")
        normalized = normalized.replace(",", "\n").replace(";", "\n")
        normalized = re.sub(r"(页面)\s*(切换到)", r"\1\n\2", normalized)
        normalized = re.sub(r"(分组)\s*(选择)", r"\1\n\2", normalized)
        normalized = re.sub(r"(后)\s*(再)", r"\1\n\2", normalized)

        raw_parts = [part.strip(" .") for part in normalized.splitlines() if part.strip(" .")]
        stages: List[Dict[str, str]] = []

        action_keywords = ("选", "双击", "进入", "切换", "键盘输入", "按", "调整", "选择", "展开", "点击", "打开", "清空", "输入", "搜索", "滚动", "确认")
        context_prefixes = ("当前", "目前", "已经", "此时")

        for part in raw_parts:
            sub_parts = self._split_stage_clause(part)
            for sub in sub_parts:
                clause = sub.strip(" .")
                if not clause:
                    continue
                if clause.startswith(context_prefixes) and any(token in clause for token in ("已经打开", "已打开", "已经进入", "已进入")):
                    continue
                if clause.startswith(context_prefixes) and not any(k in clause for k in action_keywords):
                    continue
                if not any(k in clause for k in action_keywords):
                    continue
                hint = self._infer_stage_hint(clause)
                stage = {"text": clause, "hint": hint}
                hotkey = self._extract_shortcut_from_text(clause)
                literal_text = self._extract_literal_text_from_stage(clause)
                if hotkey:
                    stage["hotkey"] = hotkey
                if literal_text:
                    stage["literal_text"] = literal_text
                stages.append(stage)

        return stages

    def _split_stage_clause(self, clause: str) -> List[str]:
        parts = [clause]
        split_patterns = [
            r"(进入[^，。；]*?页面)\s*(切换到[^，。；]*?页面)",
            r"(打开[^，。；]*?后)\s*(?:如果[^，。；]*?先清空)",
            r"(先清空[^，。；]*)\s*(再[^，。；]*)",
        ]
        changed = True
        while changed:
            changed = False
            new_parts: List[str] = []
            for part in parts:
                split_done = False
                for pattern in split_patterns:
                    match = re.search(pattern, part)
                    if match:
                        new_parts.extend([g for g in match.groups() if g and g.strip()])
                        split_done = True
                        changed = True
                        break
                if not split_done:
                    new_parts.append(part)
            parts = new_parts
        return parts

    def _infer_stage_hint(self, clause: str) -> str:
        if "双击" in clause:
            return "doubleclick"
        if any(k in clause.lower() for k in ("cmd+", "command+", "ctrl+", "alt+", "shift+")) or "键盘输入" in clause or "快捷键" in clause:
            return "hotkey"
        if "调整" in clause or "滑杆" in clause or "拖动" in clause:
            return "drag"
        if "输入" in clause:
            return "type"
        if "滚动" in clause:
            return "scroll"
        if "等待" in clause:
            return "wait"
        if any(k in clause for k in ("点击", "选择", "切换", "展开", "进入", "打开", "确认")):
            return "click"
        return "generic"

    def _advance_stage_from_tool_results(self, tool_results: Optional[List[Dict[str, Any]]]) -> None:
        if not tool_results or not self._stage_plan or self._current_stage_idx >= len(self._stage_plan):
            return

        last_id = tool_results[-1].get("tool_use_id")
        if not last_id or last_id == self._last_processed_tool_result_id:
            return
        self._last_processed_tool_result_id = last_id

        if not all(tr.get("status") == "success" for tr in tool_results):
            return
        if not self.prompt_history:
            return

        history_entry = self.prompt_history[-1]
        action_names = [
            action.get("action") or ""
            for action in (history_entry.get("actions") or [])
            if isinstance(action, dict)
        ]
        if not action_names:
            fallback_action = (history_entry.get("action") or {}).get("action") or ""
            action_names = [fallback_action]
        current_hint = self._stage_plan[self._current_stage_idx]["hint"]
        if any(self._action_matches_stage_hint(action_name, current_hint) for action_name in action_names):
            self._current_stage_idx += 1

    def _action_matches_stage_hint(self, action_name: str, hint: str) -> bool:
        if hint == "doubleclick":
            return action_name == "doubleclick"
        if hint == "hotkey":
            return action_name == "hotkey"
        if hint == "drag":
            return action_name in ("drag", "click")
        if hint == "type":
            return action_name == "type"
        if hint == "scroll":
            return action_name == "scroll"
        if hint == "wait":
            return action_name == "wait"
        if hint == "click":
            return action_name in ("click", "doubleclick", "hotkey_click")
        return action_name not in ("finish", "stop", "call_user", "")

    def _get_current_stage(self) -> Optional[Dict[str, str]]:
        if not self._stage_plan:
            return None
        if self._current_stage_idx >= len(self._stage_plan):
            return None
        return self._stage_plan[self._current_stage_idx]

    def _extract_shortcut_from_text(self, text: str) -> Optional[str]:
        patterns = [
            r"(cmd\s*\+\s*[A-Za-z0-9])",
            r"(command\s*\+\s*[A-Za-z0-9])",
            r"(ctrl\s*\+\s*[A-Za-z0-9])",
            r"(alt\s*\+\s*[A-Za-z0-9])",
            r"(shift\s*\+\s*[A-Za-z0-9])",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return re.sub(r"\s+", "", match.group(1))
        return None

    def _extract_literal_text_from_stage(self, text: str) -> Optional[str]:
        quote_match = re.search(r"[“\"]([^”\"]+)[”\"]", text)
        if quote_match:
            return quote_match.group(1).strip()
        return None

    def _build_deterministic_stage_action(self, stage: Optional[Dict[str, str]]) -> Optional[Tuple[str, str, dict]]:
        if not stage:
            return None

        if stage.get("hint") == "hotkey" and stage.get("hotkey"):
            hotkey = stage["hotkey"]
            think = f"当前子任务是显式快捷键步骤，需要直接执行 {hotkey}。"
            action_desp = f"执行快捷键 {hotkey}，完成当前子任务：{stage['text']}。"
            return think, action_desp, {"action": "hotkey", "key": hotkey}

        if stage.get("hint") == "type" and stage.get("literal_text"):
            literal_text = stage["literal_text"]
            think = f"当前子任务是显式文本输入步骤，需要原样输入“{literal_text}”。"
            action_desp = f"原样输入“{literal_text}”，完成当前子任务：{stage['text']}。"
            return think, action_desp, {"action": "type", "text": literal_text}

        return None

    # ─── Screenshot handling ──────────────────────────────────

    def _take_screenshot_b64(self) -> str:
        from visual.computer.computer_use_util import screenshot_to_bytes, b64_png
        raw_bytes = screenshot_to_bytes()
        raw_b64 = b64_png(raw_bytes)
        return self._resize_screenshot_b64(raw_b64)

    def _extract_screenshot(self, tool_results: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        if not tool_results:
            return None
        for tr in reversed(tool_results):
            b64 = tr.get("screenshot_b64")
            if b64:
                return self._resize_screenshot_b64(b64)
        return None

    def _resize_screenshot_b64(self, b64: str) -> str:
        target_w = self.cfg["SCREENSHOT_WIDTH"]
        img_bytes = base64.b64decode(b64)
        img = Image.open(io.BytesIO(img_bytes))
        if img.width == target_w:
            return b64
        ratio = target_w / img.width
        new_h = int(img.height * ratio)
        img = img.resize((target_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    # ─── Prompt building ──────────────────────────────────────

    def _build_prompt(self, task: str, current_screenshot_b64: Optional[str]) -> Tuple[str, list]:
        import platform as _platform
        images: list = []
        history_count = self.cfg["HISTORY_IMAGE_COUNT"]
        recent = self.prompt_history[-history_count:] if history_count > 0 else []
        step_memory_count = self.cfg["STEP_MEMORY_COUNT"]
        step_memory = self.prompt_history[-step_memory_count:]

        summary_parts = []
        for idx, h in enumerate(step_memory):
            step_num = self.step_count - len(step_memory) + idx + 1
            desc = h.get("desc") or ""
            actions = h.get("actions") or []
            if actions:
                action_name = " -> ".join((action.get("action") or "unknown") for action in actions)
            else:
                action = h.get("action") or {}
                action_name = action.get("action") or "unknown"
            summary_parts.append(f"第{step_num}步：动作={action_name}；说明={desc}")

        visual_parts = []
        for idx, h in enumerate(recent):
            step_num = self.step_count - len(recent) + idx + 1
            desc = h.get("desc") or ""
            if h.get("screenshot_b64"):
                images.append(h["screenshot_b64"])
                visual_parts.append(f"第{step_num}步截图：{desc}，对应截图为<image>")

        history_text = "\n".join(summary_parts) if summary_parts else "无"
        visual_history_text = "\n".join(visual_parts) if visual_parts else "无"

        instruction_parts = [f"### task: {task}"]
        if self._current_expected_result:
            instruction_parts.append(f"### expected result: {self._current_expected_result}")
        if self._stage_plan:
            current_stage = self._stage_plan[min(self._current_stage_idx, len(self._stage_plan) - 1)]
            instruction_parts.append(f"### current subtask: {current_stage['text']}")
            remaining = [s["text"] for s in self._stage_plan[self._current_stage_idx + 1:]]
            instruction_parts.append(
                "### remaining subtasks: " + (" | ".join(remaining) if remaining else "无")
            )
        task_constraints = self._build_task_constraints(task)
        if task_constraints:
            instruction_parts.append("### task constraints:")
            instruction_parts.extend(task_constraints)
        instruction_parts.append(f"### action history: {history_text}")
        instruction_parts.append(f"### recent visual history: {visual_history_text}")
        if current_screenshot_b64:
            images.append(current_screenshot_b64)
            instruction_parts.append("当前截图为<image>")

        text = self.INSTRUCTION_TEMPLATE.format(
            platform=_platform.system(),
            instruction="\n".join(instruction_parts),
        )
        return text, images

    def _build_task_constraints(self, task: str) -> List[str]:
        """Extract explicit task constraints that help small local models stay grounded."""
        constraints: List[str] = []

        if self._current_expected_result:
            constraints.append(f"- 最终完成条件：{self._current_expected_result}")

        group_patterns = [
            r"确认([^，。；]+?)分组展开",
            r"展开([^，。；]+?)分组",
        ]
        seen_groups = set()
        for pattern in group_patterns:
            for match in re.finditer(pattern, task):
                group_name = match.group(1).strip()
                if group_name and group_name not in seen_groups:
                    seen_groups.add(group_name)
                    constraints.append(f"- 目标分组是“{group_name}”。如果该分组已经展开并且子控件可见，不要再次点击它的标题。")

        slider_match = re.search(r"调整([^，。；]+?)滑杆至(\d+)", task)
        if not slider_match and self._current_expected_result:
            slider_match = re.search(r"([^，。；]+?)调整至(\d+)", self._current_expected_result)
        if slider_match:
            slider_name = slider_match.group(1).strip()
            slider_value = slider_match.group(2).strip()
            constraints.append(f"- 精确目标滑杆名称是“{slider_name}”，目标数值是 {slider_value}。")
            constraints.append(f"- 只能操作屏幕上标签文字与“{slider_name}”完全一致的那一行。")
            constraints.append(f"- 如果同时看到总滑杆/父滑杆和名称相近的子滑杆，不要把子滑杆当成“{slider_name}”。")
            constraints.append(f"- 只有当标签为“{slider_name}”的那一行可见数值达到 {slider_value} 时，才允许结束任务。")

        page_match = re.search(r"切换到([^，。；]+?)页面", task)
        if page_match:
            page_name = page_match.group(1).strip()
            constraints.append(f"- 在执行后续调节前，先确认当前页面确实是“{page_name}”页面。")

        if self._stage_plan and self._current_stage_idx < len(self._stage_plan):
            current_stage = self._stage_plan[self._current_stage_idx]["text"]
            constraints.append(f"- 当前只专注完成这个子任务：“{current_stage}”。")
            constraints.append("- 在当前子任务明显完成前，不要提前跳到后面的步骤。")
            if self._current_stage_idx < len(self._stage_plan) - 1:
                constraints.append("- 在所有子任务完成前，不要输出 finish()。")

        return constraints

    # ─── Inference ────────────────────────────────────────────

    def _infer(self, user_text: str, images: list) -> str:
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ]

        pil_images = []
        for b64 in images:
            img_bytes = base64.b64decode(b64)
            pil_images.append(Image.open(io.BytesIO(img_bytes)))

        prompt = self.processor.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        # Replace <image> placeholders with Qwen3-VL vision tokens
        org_placeholder = "<image>"
        new_placeholder = "<|vision_start|><|image_pad|><|vision_end|>"
        pi = len(pil_images)
        while pi > 0:
            pi -= 1
            pos = prompt.rfind(org_placeholder)
            if pos >= 0:
                prompt = prompt[:pos] + prompt[pos:].replace(org_placeholder, new_placeholder, 1)
            else:
                break

        result = self._custom_generate(
            self.model, self.processor, prompt,
            pil_images if pil_images else None,
            max_tokens=self.cfg["MAX_NEW_TOKENS"],
            temperature=self.cfg["TEMPERATURE"],
            top_p=self.cfg["TOP_P"],
            prefill_step_size=2048,
        )
        gen_tokens = getattr(result, "generation_tokens", 0)
        gen_tps = getattr(result, "generation_tps", 0)
        peak_mem = getattr(result, "peak_memory", 0)
        print(f"  [decode] {gen_tokens} tokens, {gen_tps:.1f} tok/s, peak_mem={peak_mem:.1f}GB")
        return result.text

    # ─── Response parsing ─────────────────────────────────────

    def _parse_response(self, text: str) -> dict:
        think = self._extract_tag(text, "think") or ""
        action_desp = self._extract_tag(text, "action_desp") or ""
        action_raw = self._extract_tag(text, "action") or ""
        actions = []
        if action_raw:
            # Match each action function call: name(...) allowing nested quotes/newlines
            for m in re.finditer(r"(\w+\(.*?\))(?=\s*\n\s*\w+\(|\s*$)", action_raw.strip(), re.DOTALL):
                parsed = self._parse_action(m.group(1).strip())
                if parsed:
                    actions.append(parsed)
        return {"think": think.strip(), "action_desp": action_desp.strip(), "actions": actions}

    def _extract_tag(self, text: str, tag: str) -> Optional[str]:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
        return m.group(1) if m else None

    def _parse_box(self, box_str: str) -> list:
        m = re.search(r"\((\d+)\s*,\s*(\d+)\)", box_str)
        if not m:
            return [0, 0]
        return [int(m.group(1)), int(m.group(2))]

    def _parse_hotkey_spec(self, key_spec: str) -> Tuple[List[str], List[str]]:
        """Parse hotkey text like 'cmd+c' into executor modifiers/mains."""
        if not key_spec:
            return [], []

        alias_map = {
            "cmd": "cmd",
            "command": "cmd",
            "meta": "cmd",
            "win": "cmd",
            "super": "cmd",
            "ctrl": "ctrl",
            "control": "ctrl",
            "alt": "alt",
            "option": "alt",
            "opt": "alt",
            "shift": "shift",
            "enter": "enter",
            "return": "enter",
            "esc": "esc",
            "escape": "esc",
            "space": "space",
            "tab": "tab",
            "backspace": "backspace",
            "delete": "delete",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
        }
        modifier_keys = {"cmd", "ctrl", "alt", "shift"}

        parts = [p.strip().lower() for p in re.split(r"(?:\s*\+\s*|\s+)", key_spec) if p.strip()]
        modifiers: List[str] = []
        mains: List[str] = []
        for part in parts:
            key_name = alias_map.get(part, part)
            if key_name in modifier_keys:
                if key_name not in modifiers:
                    modifiers.append(key_name)
            else:
                mains.append(key_name)

        return modifiers, mains

    def _parse_action(self, action_str: str) -> Optional[dict]:
        action_str = action_str.strip()
        m = re.match(r"(\w+)\((.*)\)$", action_str, re.DOTALL)
        if not m:
            return self._parse_fallback_action(action_str)

        func_name = m.group(1)
        args_str = m.group(2).strip()

        kwargs = {}
        for km in re.finditer(r"(\w+)\s*=\s*'(.*?)'", args_str, re.DOTALL):
            kwargs[km.group(1)] = km.group(2)

        if func_name in ("click", "doubleclick", "hover"):
            return {"action": func_name, "coords": self._parse_box(kwargs.get("start_box", ""))}
        if func_name == "triple_click":
            return {"action": "triple_click", "coords": self._parse_box(kwargs.get("start_box", ""))}
        if func_name == "right_single":
            return {"action": "right_click", "coords": self._parse_box(kwargs.get("start_box", ""))}
        if func_name == "hotkey_click":
            return {"action": "hotkey_click", "coords": self._parse_box(kwargs.get("start_box", "")), "key": kwargs.get("key", "")}
        if func_name == "type":
            return {"action": "type", "text": kwargs.get("content", "")}
        if func_name == "hotkey":
            return {"action": "hotkey", "key": kwargs.get("key", "")}
        if func_name == "scroll":
            amount = kwargs.get("amount", "5")
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                amount = 5
            result = {"action": "scroll", "direction": kwargs.get("direction", "down"), "amount": amount}
            box = kwargs.get("start_box", "")
            if box:
                result["coords"] = self._parse_box(box)
            return result
        if func_name == "drag":
            return {
                "action": "drag",
                "start": self._parse_box(kwargs.get("start_box", "")),
                "end": self._parse_box(kwargs.get("end_box", "")),
            }
        if func_name == "wait":
            duration = kwargs.get("duration", "5")
            try:
                duration = float(duration)
            except (ValueError, TypeError):
                duration = 5.0
            return {"action": "wait", "duration": duration}
        if func_name == "finish":
            return {"action": "finish"}
        if func_name == "open_app":
            return {"action": "open_app", "app_name": kwargs.get("app_name", "")}
        if func_name == "open_url":
            return {"action": "open_url", "url": kwargs.get("url", "")}
        if func_name == "stop":
            return {"action": "stop", "reason": kwargs.get("reason", "")}
        if func_name == "call_user":
            return {"action": "call_user"}
        return None

    def _parse_fallback_action(self, action_str: str) -> Optional[dict]:
        """Parse looser action formats such as 'scroll;dir=down;amount=3'."""
        if not action_str or ";" not in action_str:
            return None

        parts = [part.strip() for part in action_str.split(";") if part.strip()]
        if not parts:
            return None

        func_name = parts[0].lower()
        kwargs = {}
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            kwargs[key.strip().lower()] = value.strip().strip("'\"")

        if func_name == "scroll":
            amount = kwargs.get("amount", "5")
            try:
                amount = int(amount)
            except (ValueError, TypeError):
                amount = 5
            result = {
                "action": "scroll",
                "direction": kwargs.get("direction") or kwargs.get("dir", "down"),
                "amount": amount,
            }
            return result

        if func_name == "wait":
            duration = kwargs.get("duration", kwargs.get("seconds", "5"))
            try:
                duration = float(duration)
            except (ValueError, TypeError):
                duration = 5.0
            return {"action": "wait", "duration": duration}

        return None

    # ─── Action conversion: Qwen3-VL → Claude format ─────────

    def _norm_coord(self, x: int, y: int) -> list:
        """Convert [0,1000] normalised coords to 1280x720 executor space.

        The executor then scales from 1280x720 to actual screen pixels.
        """
        return [int(x / 1000 * AUTOMATION_CONFIG["SCREEN_SCALE_WIDTH"]),
                int(y / 1000 * AUTOMATION_CONFIG["SCREEN_SCALE_HEIGHT"])]

    def _make_tool_action(self, input_dict: dict) -> dict:
        return {
            "name": "computer",
            "input": input_dict,
            "id": str(uuid.uuid4()),
            "action_type": "tool_use",
        }

    def _determine_status(self, actions: List[Dict[str, Any]]) -> str:
        for a in actions:
            at = (a.get("action_type") or "").upper()
            if at == "DONE":
                return "DONE"
            if at == "STOP":
                return "STOP"
            if at == "FAIL":
                return "FAIL"
            if at == "CALL_USER":
                return "CALL_USER"
        return "RUNNING"

    def _format_action_desc(self, actions: List[Dict[str, Any]]) -> str:
        """Format action list into human-readable string like 'left_click(432, 265)'."""
        if not actions:
            return ""
        a = actions[0]
        at = (a.get("action_type") or "").upper()
        if at in ("DONE", "STOP", "FAIL", "CALL_USER"):
            return at
        inp = a.get("input", {})
        name = a.get("name", "")
        if name == "open_app":
            return f"open_app(\"{inp.get('app_name', '')}\")"
        if name == "open_url":
            return f"open_url(\"{inp.get('url', '')}\")"
        action = inp.get("action", "unknown")
        coord = inp.get("coordinate")
        if coord:
            return f"{action}({coord[0]}, {coord[1]})"
        if action == "key":
            combo = self._format_key_combo(inp.get("modifiers"), inp.get("mains"))
            return f'key("{combo}")' if combo else "key"
        text = inp.get("text")
        if text:
            return f"{action}(\"{text[:30]}\")"
        direction = inp.get("scroll_direction")
        if direction:
            return f"{action} {direction}"
        return action

    def _format_key_combo(self, modifiers: Optional[List[str]], mains: Optional[List[str]]) -> str:
        parts: List[str] = []
        for token in (modifiers or []):
            if token:
                parts.append(str(token))
        for token in (mains or []):
            if token:
                parts.append(str(token))
        return "+".join(parts)

    def _convert_action(self, action: dict) -> List[Dict[str, Any]]:
        """Convert parsed Qwen3-VL action to Claude-compatible action list."""
        act = action["action"]

        if act == "finish":
            return [{"action_type": "DONE"}]
        if act == "open_app":
            return [{
                "name": "open_app",
                "input": {"app_name": action.get("app_name", "")},
                "id": str(uuid.uuid4()),
                "action_type": "tool_use",
            }]
        if act == "open_url":
            return [{
                "name": "open_url",
                "input": {"url": action.get("url", "")},
                "id": str(uuid.uuid4()),
                "action_type": "tool_use",
            }]
        if act == "stop":
            return [{"action_type": "STOP"}]
        if act == "call_user":
            return [{"action_type": "CALL_USER"}]

        if act == "click":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "left_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "doubleclick":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "double_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "triple_click":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "triple_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "right_click":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "right_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "hover":
            coords = action.get("coords", [0, 0])
            return [self._make_tool_action({
                "action": "mouse_move",
                "coordinate": self._norm_coord(coords[0], coords[1]),
            })]

        if act == "hotkey_click":
            coords = action.get("coords", [0, 0])
            modifiers, _ = self._parse_hotkey_spec(action.get("key", ""))
            return [self._make_tool_action({
                "action": "left_click",
                "coordinate": self._norm_coord(coords[0], coords[1]),
                "modifiers": modifiers,
            })]

        if act == "type":
            return [self._make_tool_action({
                "action": "type",
                "text": action.get("text", ""),
            })]

        if act == "hotkey":
            modifiers, mains = self._parse_hotkey_spec(action.get("key", ""))
            return [self._make_tool_action({
                "action": "key",
                "modifiers": modifiers,
                "mains": mains,
            })]

        if act == "scroll":
            direction = action.get("direction", "down")
            amount = action.get("amount", 3)
            coords = action.get("coords")
            coordinate = self._norm_coord(coords[0], coords[1]) if coords else [640, 360]
            return [self._make_tool_action({
                "action": "scroll",
                "scroll_direction": direction,
                "coordinate": coordinate,
                "scroll_amount": amount,
            })]

        if act == "drag":
            start = action.get("start", [0, 0])
            end = action.get("end", [0, 0])
            return [self._make_tool_action({
                "action": "left_click_drag",
                "start_coordinate": self._norm_coord(start[0], start[1]),
                "coordinate": self._norm_coord(end[0], end[1]),
            })]

        if act == "wait":
            duration = action.get("duration", 5)
            return [self._make_tool_action({
                "action": "wait",
                "duration": duration,
            })]

        return [{"action_type": "FAIL"}]
