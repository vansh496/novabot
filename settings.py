"""Shared settings store.

Dono cheezein (bot aur dashboard) isi module se settings padhte/likhte hain.
File change hote hi dono ko naye settings mil jaate hain - restart ki zaroorat nahi.
"""

from __future__ import annotations

import copy
import json
import os
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

_lock = threading.RLock()
_cache = {"data": {}, "mtime": 0.0}


def default_settings() -> dict:
    """Har guild ke liye default (shirtkha) settings."""
    return {
        "welcome": {
            "enabled": False,
            "channel_id": 0,
            "message": "Welcome {user} to **{server}**! You are member #{member_count}.",
            "use_embed": True,
            "embed_color": "#57F287",
            "dm_enabled": False,
            "dm_message": "Welcome to **{server}**, {username}! Please read the rules and enjoy your stay.",
            "leave_enabled": False,
            "leave_channel_id": 0,
            "leave_message": "{username} left **{server}**. Member count: {member_count}",
        },
        "verification": {
            "enabled": False,
            "channel_id": 0,
            "role_id": 0,
            "message": "Click the button below to verify yourself and get access to the server.",
            "embed_color": "#5865F2",
        },
        "tickets": {
            "enabled": False,
            "panel_channel_id": 0,
            "category_id": 0,
            "support_role_id": 0,
            "log_channel_id": 0,
            "message": "Need help? Click the button below to open a private ticket with the staff.",
            "embed_color": "#5865F2",
        },
        "antinuke": {
            "enabled": False,
            "alert_channel_id": 0,
            # ban | kick | none (sirf alert)
            "action": "ban",
            # True = kisi ne bhi bot add / ban / kick / channel ya role
            # banaya-deleted to 1 second ke andar foran ban (admin bhi nahi bachega)
            "instant_ban": True,
            "window_seconds": 60,
            "max_bans": 3,
            "max_kicks": 5,
            # Kisi ne bot add kiya (gateway event miss ho jaye to yehi fallback)
            "max_bots": 1,
            "max_channels": 5,
            "max_roles": 3,
            # True = jo log admin hain unhe chhod do (safe mode)
            "ignore_admins": True,
            # True = doosre bots (mod bots) ko chhod do
            "ignore_bots": True,
            # Yahan trust karne wale user IDs (strings) hoti hain
            "whitelist": [],
        },
    }


SECTIONS = tuple(default_settings().keys())


def _deep_merge(default: dict, custom: dict) -> dict:
    result = copy.deepcopy(default)
    for key, value in custom.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _coerce(default_value, new_value):
    """Naye value ko default ke type mein badalta hai (dashboard se aane par)."""
    if isinstance(default_value, bool):
        if isinstance(new_value, str):
            return new_value.strip().lower() in ("1", "true", "yes", "on")
        return bool(new_value)
    if isinstance(default_value, int):
        try:
            return int(new_value)
        except (TypeError, ValueError):
            return int(default_value)
    if isinstance(default_value, list):
        if isinstance(new_value, list):
            return [str(v).strip() for v in new_value if str(v).strip()]
        if new_value is None:
            return []
        return [v.strip() for v in str(new_value).replace(",", "\n").splitlines() if v.strip()]
    if new_value is None:
        return default_value
    return str(new_value)


def _load(force: bool = False) -> dict:
    with _lock:
        try:
            mtime = os.path.getmtime(SETTINGS_FILE)
        except OSError:
            mtime = 0.0

        if not force and _cache["data"] and mtime == _cache["mtime"]:
            return _cache["data"]

        data = {}
        if mtime:
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                    if isinstance(loaded, dict):
                        data = loaded
            except (OSError, json.JSONDecodeError):
                data = _cache["data"] or {}

        _cache["data"] = data
        _cache["mtime"] = mtime
        return data


def _save(data: dict) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, SETTINGS_FILE)
    _cache["data"] = data
    try:
        _cache["mtime"] = os.path.getmtime(SETTINGS_FILE)
    except OSError:
        _cache["mtime"] = 0.0


def ensure_file() -> None:
    with _lock:
        if not os.path.exists(SETTINGS_FILE):
            _save({})


def get(guild_id) -> dict:
    """Guild ki poori settings (defaults ke saath merge karke)."""
    data = _load()
    raw = data.get(str(guild_id), {})
    if not isinstance(raw, dict):
        raw = {}
    return _deep_merge(default_settings(), raw)


def get_section(guild_id, section: str) -> dict:
    if section not in SECTIONS:
        raise KeyError(section)
    return get(guild_id)[section]


def set_section(guild_id, section: str, values: dict) -> dict:
    """Ek section update karke file mein save karta hai. (bot live pick kar leta hai)"""
    if section not in SECTIONS:
        raise KeyError(section)
    if not isinstance(values, dict):
        raise TypeError("values dict hona chahiye")

    defaults = default_settings()[section]
    clean = {}
    for key, value in values.items():
        if key not in defaults:
            continue
        clean[key] = _coerce(defaults[key], value)
    if not clean:
        raise ValueError("koi valid field nahi mila")

    with _lock:
        data = _load(force=True)
        guild_data = data.setdefault(str(guild_id), {})
        if not isinstance(guild_data, dict):
            guild_data = {}
            data[str(guild_id)] = guild_data
        current = guild_data.get(section)
        if not isinstance(current, dict):
            current = {}
        merged = copy.deepcopy(defaults)
        merged.update({k: _coerce(defaults[k], v) for k, v in current.items() if k in defaults})
        merged.update(clean)
        guild_data[section] = merged
        _save(data)

    return get(guild_id)


def guild_ids() -> list:
    return list(_load().keys())
