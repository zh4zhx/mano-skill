# Mano-P

Desktop GUI automation model based on Qwen3-VL. Takes a screenshot and task description, outputs the next GUI action (click, type, scroll, drag, etc.).

## Quick Start

### Requirements

- macOS with Apple Silicon (M1+)
- Python >= 3.12

### Installation

**With Cider (recommended, includes W8A8 acceleration):**

```bash
pip install mlx-vlm
pip install git+https://github.com/Mininglamp-AI/cider.git
```

**Without Cider (FP16, PyTorch):**

```bash
pip install transformers torch torchvision qwen-vl-utils
```

### Single-Step Demo (FP16, PyTorch)

```python
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
from PIL import Image

# 1. Load model
model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
    "Mininglamp-2718/Mano-P",
    torch_dtype="auto",
    device_map="auto",
)
processor = AutoProcessor.from_pretrained("Mininglamp-2718/Mano-P")

# 2. Load a screenshot
img = Image.open("screenshot.png")
ratio = 1280 / img.width
img = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)

# 3. Build prompt
task = "Click the search bar and type hello"

prompt_text = f"""You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
<think>thoughts</think>
<action_desp>action description</action_desp>
<action>action call</action>

## Action Space
click(start_box='<|box_start|>(x1,y1)<|box_end|>')
type(content='')
hotkey(key='')
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up', amount='3')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x2,y2)<|box_end|>')
finish()

## User Instruction:
### task: {task}
### action history: None
Current screenshot: <image>"""

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": [
        {"type": "image", "image": img},
        {"type": "text", "text": prompt_text},
    ]},
]

# 4. Run inference
text_input = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
image_inputs, video_inputs = process_vision_info(messages)
inputs = processor(
    text=[text_input], images=image_inputs, videos=video_inputs,
    padding=True, return_tensors="pt",
).to(model.device)

output_ids = model.generate(**inputs, max_new_tokens=512, temperature=0.0, do_sample=False)
output_ids = output_ids[:, inputs.input_ids.shape[1]:]
output = processor.batch_decode(output_ids, skip_special_tokens=True)[0]

print(output)
```

### Single-Step Demo (with Cider)

```python
import mlx_vlm as pm
from vlm_service import custom_generate
from PIL import Image

# 1. Load model
model, processor = pm.load("Mininglamp-2718/Mano-P")

# 2. Load a screenshot (or any desktop screenshot image)
img = Image.open("screenshot.png")
# Resize to 1280px width (model's expected input resolution)
ratio = 1280 / img.width
img = img.resize((1280, int(img.height * ratio)), Image.LANCZOS)

# 3. Build prompt
task = "Click the search bar and type hello"

prompt_text = f"""You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
<think>thoughts</think>
<action_desp>action description</action_desp>
<action>action call</action>

## Action Space
click(start_box='<|box_start|>(x1,y1)<|box_end|>')
type(content='')
hotkey(key='')
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up', amount='3')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x2,y2)<|box_end|>')
finish()

## User Instruction:
### task: {task}
### action history: None
Current screenshot: <image>"""

messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": prompt_text},
]
prompt = processor.tokenizer.apply_chat_template(
    messages, tokenize=False, add_generation_prompt=True
)
prompt = prompt.replace("<image>", "<|vision_start|><|image_pad|><|vision_end|>")

# 4. Run inference
result = custom_generate(
    model, processor, prompt,
    [img],
    max_tokens=512,
    temperature=0.0,
    prefill_step_size=2048,
)

print(f"Tokens: {result.generation_tokens}, Speed: {result.generation_tps:.1f} tok/s")
print(result.text)
```

### Multi-Step Agent Loop

The model is designed for multi-turn interaction: execute an action, take a new screenshot, feed it back with action history.

```python
import mlx_vlm as pm
from vlm_service import custom_generate
from PIL import Image
import re

model, processor = pm.load("Mininglamp-2718/Mano-P")

SYSTEM_PROMPT = "You are a helpful assistant."

INSTRUCTION_TEMPLATE = """You are a GUI agent. You are given a task and your action history, with screenshots. You need to perform the next action to complete the task.

## Output Format
<think>thoughts</think>
<action_desp>action description</action_desp>
<action>action call</action>

## Action Space
click(start_box='<|box_start|>(x1,y1)<|box_end|>')
type(content='')
hotkey(key='')
scroll(start_box='<|box_start|>(x1,y1)<|box_end|>', direction='down or up', amount='3')
drag(start_box='<|box_start|>(x1,y1)<|box_end|>', end_box='<|box_start|>(x2,y2)<|box_end|>')
finish()
stop(reason='')

## User Instruction:
### task: {task}
### action history: {history}
Current screenshot: <image>"""


def resize(img, width=1280):
    ratio = width / img.width
    return img.resize((width, int(img.height * ratio)), Image.LANCZOS)


def build_prompt(task, history_steps, current_img):
    """Build prompt with action history and current screenshot."""
    images = []

    # Include last history screenshot + current screenshot
    history_lines = []
    for i, step in enumerate(history_steps):
        if i == len(history_steps) - 1 and step.get("screenshot"):
            images.append(step["screenshot"])
            history_lines.append(f"Step {i+1}: {step['desc']}, screenshot: <image>")
        else:
            history_lines.append(f"Step {i+1}: {step['desc']}")

    history_text = "\n".join(history_lines) if history_lines else "None"
    images.append(current_img)

    text = INSTRUCTION_TEMPLATE.format(task=task, history=history_text)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    prompt = processor.tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    # Replace <image> placeholders with vision tokens (right-to-left)
    for _ in range(len(images)):
        pos = prompt.rfind("<image>")
        if pos >= 0:
            prompt = prompt[:pos] + "<|vision_start|><|image_pad|><|vision_end|>" + prompt[pos + 7:]
    return prompt, images


def parse_output(text):
    """Extract think, action_desp, action from model output."""
    def extract(tag):
        m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
        return m.group(1).strip() if m else ""
    return extract("think"), extract("action_desp"), extract("action")


# --- Agent loop ---
task = "Open Safari and search for 'MLX framework'"
history = []
max_steps = 10

for step in range(max_steps):
    # Take screenshot (replace with your own screenshot capture)
    screenshot = resize(Image.open(f"step_{step}.png"))

    # Build prompt and run inference
    prompt, images = build_prompt(task, history, screenshot)
    result = custom_generate(
        model, processor, prompt, images,
        max_tokens=512, temperature=0.0, prefill_step_size=2048,
    )

    think, action_desp, action = parse_output(result.text)
    print(f"[Step {step+1}] {action_desp}")
    print(f"  Action: {action}")

    # Check terminal actions
    if action.startswith("finish"):
        print("Task completed!")
        break
    if action.startswith("stop"):
        print("Task infeasible.")
        break

    # Record history for next step
    history.append({"desc": action_desp, "screenshot": screenshot})

    # >>> Execute the action on screen, then loop back to take new screenshot <<<
```

### Output Format

The model outputs structured XML:

```xml
<think>The search bar is at the top of the page...</think>
<action_desp>Click the search bar to focus it</action_desp>
<action>click(start_box='<|box_start|>(500,38)<|box_end|>')</action>
```

Coordinates are normalized to `[0, 1000]` range. To convert to pixel coordinates:

```python
pixel_x = int(x / 1000 * screen_width)
pixel_y = int(y / 1000 * screen_height)
```

### W8A8 Acceleration (M5+ only)

On Apple M5 or later, enable INT8 acceleration for ~15-19% faster prefill:

```python
from cider import convert_model, is_available

if is_available():
    convert_model(model.language_model)
```

## Full Action Space

| Action | Syntax | Description |
|--------|--------|-------------|
| click | `click(start_box='<\|box_start\|>(x,y)<\|box_end\|>')` | Left click |
| doubleclick | `doubleclick(start_box='<\|box_start\|>(x,y)<\|box_end\|>')` | Double click |
| triple_click | `triple_click(start_box='<\|box_start\|>(x,y)<\|box_end\|>')` | Triple click (select line) |
| right_single | `right_single(start_box='<\|box_start\|>(x,y)<\|box_end\|>')` | Right click |
| hover | `hover(start_box='<\|box_start\|>(x,y)<\|box_end\|>')` | Mouse hover |
| type | `type(content='text')` | Type text |
| hotkey | `hotkey(key='cmd+c')` | Keyboard shortcut |
| hotkey_click | `hotkey_click(start_box='<\|box_start\|>(x,y)<\|box_end\|>', key='shift')` | Modifier + click |
| scroll | `scroll(start_box='<\|box_start\|>(x,y)<\|box_end\|>', direction='down', amount='3')` | Scroll |
| drag | `drag(start_box='<\|box_start\|>(x1,y1)<\|box_end\|>', end_box='<\|box_start\|>(x2,y2)<\|box_end\|>')` | Drag and drop |
| wait | `wait(duration='2')` | Wait (seconds) |
| finish | `finish()` | Task completed |
| stop | `stop(reason='...')` | Task infeasible |
| call_user | `call_user()` | Request human help |
