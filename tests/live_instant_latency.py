"""Live latency test: gateway audit event -> Anti-Nuke INSTANT decision.

SAFETY: yahan khud BOT ek test channel banata aur delete karta hai, to actor = bot
= protected -> kisi member par ban NAHI lagta. Sirf bot ke log ke timestamp se
end-to-end latency (REST call -> handler) measure hoti hai.

Chalane ke liye bot ON chahiye (bot_err.log likh raha hona chahiye).
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import requests  # noqa: E402

TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()
GID = "1554407195037401200"
LOG = os.path.join(ROOT, "bot_err.log")
API = f"https://discord.com/api/v10/guilds/{GID}"
API_BASE = "https://discord.com/api/v10"
H = {"Authorization": f"Bot {TOKEN}", "User-Agent": "NovaBot-latency-test/1.0"}

results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((bool(ok), name))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("   -> " + str(extra)) if (extra and not ok) else ""))


def log_size() -> int:
    try:
        return os.path.getsize(LOG)
    except OSError:
        return 0


def wait_for_instant_line(start_pos: int, timeout: float = 5.0):
    """Naya INSTANT log line dhundhta hai -> (local_time, naya_pos) ya None."""
    pos = start_pos
    end = time.time() + timeout
    while time.time() < end:
        try:
            with open(LOG, "rb") as f:
                f.seek(pos)
                chunk = f.read()
                pos = f.tell()
        except OSError:
            time.sleep(0.05)
            continue
        for line in chunk.split(b"\n"):
            if b"Anti-Nuke INSTANT:" not in line:
                continue
            m = re.match(rb"^(\d{2}):(\d{2}):(\d{2})\.(\d{3})", line.strip())
            if not m:
                continue
            h, mi, s, ms = (int(x) for x in m.groups())
            return datetime.time(h, mi, s, ms * 1000), line.decode("utf-8", "replace"), pos
        time.sleep(0.03)
    return None


def delta_ms(t0_epoch: float, log_time: datetime.time) -> float:
    """REST call ke turant baad ka time vs handler ka log time (ms)."""
    now = datetime.datetime.fromtimestamp(t0_epoch)
    log_dt = datetime.datetime.combine(now.date(), log_time)
    return (log_dt - now).total_seconds() * 1000


def main() -> int:
    if not os.path.exists(LOG):
        print(f"FAIL: {LOG} nahi mila - bot running hai?")
        return 1

    print("Anti-Nuke INSTANT - LIVE latency test")
    print("Actor = bot (protected) -> koi member ban nahi hoga\n")
    print(f"log: {LOG}   size={log_size()} bytes\n")

    attempts = [
        ("channel_create", "⏱️ antinuke-latency-test"),
        ("channel_delete", None),
        ("channel_create", "⏱️ antinuke-latency-test-2"),
        ("channel_delete", None),
    ]
    last_channel = None
    made_channels = []

    for action, name in attempts:
        pos = log_size()
        t0 = time.time()
        try:
            if action == "channel_create":
                r = requests.post(
                    f"{API}/channels",
                    headers=H,
                    json={"name": name, "type": 0, "parent_id": None},
                    timeout=15,
                )
                r.raise_for_status()
                last_channel = r.json()["id"]
                made_channels.append(last_channel)
            else:
                if last_channel is None:
                    continue
                # DELETE /channels/{id} (guilds/{gid}/channels/{id} 404 deta hai)
                r = requests.delete(f"{API_BASE}/channels/{last_channel}", headers=H, timeout=15)
                r.raise_for_status()
                last_channel = None
        except (urllib.error.URLError, requests.RequestException) as exc:
            check(f"{action} REST call", False, exc)
            continue

        found = wait_for_instant_line(pos, timeout=5.0)
        if found is None:
            check(f"{action}: INSTANT log line aayi", False,
                  "5s mein koi line nahi (poll ne pehle le liya ya event nahi aaya)")
            continue
        log_time, line, _ = found
        d = delta_ms(t0, log_time)
        print(f"        t0={datetime.datetime.fromtimestamp(t0):%H:%M:%S.%f}  "
              f"handler={log_time:%H:%M:%S.%f}  -> {d:.0f} ms")
        print(f"        {line.strip()}")
        check(f"{action}: INSTANT line < 1000 ms (got {d:.0f} ms)", 0 <= d < 1000, f"{d:.0f} ms")
        check(f"{action}: protected (member ban NAHI hua)", b"protected" in line.encode(), line)

    # cleanup: bache hue test channels hatao
    for cid in made_channels:
        try:
            requests.delete(f"{API_BASE}/channels/{cid}", headers=H, timeout=15)
        except requests.RequestException:
            pass

    # safety: bans list ab bhi clean honi chahiye
    try:
        bans = requests.get(f"{API}/bans", headers=H, timeout=15).json()
        check("koi accidental ban nahi hua (bans clean)", isinstance(bans, list) and len(bans) == 0, bans)
    except requests.RequestException as exc:
        check("bans list check", False, exc)

    passed = sum(1 for ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 50)
    for ok, name in results:
        if not ok:
            print("  FAIL:", name)
    print(f"RESULT: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
