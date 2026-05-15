"""Platform-aware key normalization for actions (ported from mano-afk-public)."""

from copy import deepcopy


def normalize_actions(actions):
    """Normalize key/modifier names for the current platform."""
    click_actions = {"left_click", "right_click", "double_click", "middle_click", "triple_click"}

    normalized = []
    for a in actions or []:
        item = deepcopy(a)
        tool_input = item.get("input") or {}
        action = str(tool_input.get("action") or "").strip().lower()

        if action == "key":
            mods, mains = _normalize_key_fields(tool_input)
            tool_input["modifiers"] = mods
            tool_input["mains"] = mains

        elif action in click_actions:
            mods = _normalize_click_modifiers(tool_input)
            tool_input["modifiers"] = mods

        item["input"] = tool_input
        normalized.append(item)

    return normalized


def _normalize_key_fields(tool_input):
    combo_text = tool_input.get("text")
    if combo_text:
        return _normalize_combo_to_mods_and_mains(combo_text)

    modifiers = _normalize_modifier_list(tool_input.get("modifiers"))
    mains = _normalize_main_list(tool_input.get("mains"))
    return modifiers, mains


def _normalize_click_modifiers(tool_input):
    combo_text = tool_input.get("text")
    if combo_text:
        modifiers, _ = _normalize_combo_to_mods_and_mains(combo_text)
        return modifiers
    return _normalize_modifier_list(tool_input.get("modifiers"))


def _normalize_combo_to_mods_and_mains(combo):
    parts = _split_combo(combo)
    modifiers = []
    mains = []
    for p in parts:
        k = _normalize_key_token(p)
        if not k:
            continue
        if _is_modifier(k):
            if k not in modifiers:
                modifiers.append(k)
        else:
            mains.append(k)
    return modifiers, mains


def _normalize_modifier_list(modifiers):
    normalized = []
    for token in _split_combo(modifiers):
        key = _normalize_key_token(token)
        if key and _is_modifier(key) and key not in normalized:
            normalized.append(key)
    return normalized


def _normalize_main_list(mains):
    normalized = []
    for token in _split_combo(mains):
        key = _normalize_key_token(token)
        if key and not _is_modifier(key):
            normalized.append(key)
    return normalized


def _split_combo(combo):
    if combo is None:
        return []
    if isinstance(combo, list):
        return [str(x).strip() for x in combo if str(x).strip()]
    s = str(combo).strip()
    if "+" in s:
        return [x.strip() for x in s.split("+") if x.strip()]
    return [x.strip() for x in s.split() if x.strip()]


def _is_modifier(k):
    return k in {
        "cmd", "ctrl", "alt", "shift",
        "cmd_l", "cmd_r", "ctrl_l", "ctrl_r",
        "alt_l", "alt_r", "alt_gr", "shift_l", "shift_r",
    }


def _normalize_key_token(k):
    k = str(k).strip().lower()
    k = k.replace("-", "_").replace(" ", "_")

    if k in ("command", "cmd"):
        return "cmd"
    if k in ("control", "ctl", "ctrl"):
        return "ctrl"
    if k in ("option", "opt"):
        return "alt"
    if k in ("meta", "super", "win"):
        return "cmd"

    if k in ("command_l", "cmd_l"):
        return "cmd_l"
    if k in ("command_r", "cmd_r"):
        return "cmd_r"
    if k in ("control_l", "ctl_l", "ctrl_l"):
        return "ctrl_l"
    if k in ("control_r", "ctl_r", "ctrl_r"):
        return "ctrl_r"
    if k in ("meta_l", "super_l", "win_l"):
        return "cmd_l"
    if k in ("meta_r", "super_r", "win_r"):
        return "cmd_r"
    if k in ("option_l", "opt_l"):
        return "alt_l"
    if k in ("option_r", "opt_r"):
        return "alt_r"
    if k == "altgr":
        return "alt_gr"

    alias_map = {
        "return": "enter",
        "escape": "esc",
        "spacebar": "space",
        "arrowup": "up", "arrow_up": "up",
        "arrowdown": "down", "arrow_down": "down",
        "arrowleft": "left", "arrow_left": "left",
        "arrowright": "right", "arrow_right": "right",
        "pageup": "page_up", "pgup": "page_up",
        "pagedown": "page_down", "pgdn": "page_down",
        "del": "delete",
    }
    return alias_map.get(k, k)
