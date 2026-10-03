"""Live test: Administrator role grant -> Anti-Nuke INSTANT path.

SAFETY: saare kadam khud BOT karta hai (REST se), to actor = bot = protected ->
kisi member par ban NAHI lagta. Test ke baad sab kuch (role + membership) wapas
le liya jata hai. Sirf log timestamp se latency + detection check hoti hai.

Steps:
  1) role create           -> INSTANT (protected)
  2) role ko admin banaya  -> role_update DETECT -> INSTANT (protected)
  3) bot ko woh role di    -> member_role_update DETECT -> INSTANT (protected)
  4) role wapas li         -> admin nahi diya -> skip (expected)
  5) role delete           -> INSTANT (protected)

Chalane ke liye bot ON chahiye.
"""
from __future__ import annotations

import datetime
import os
import re
import sys
import time

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
BOT_ID = "1546153129043562506"
ROLE_NAME = "antinuke-admin-test"
ADMIN_BIT = 8  # PermissionFlags.administrator
LOG = os.path.join(ROOT, "bot_err.log")
API = f"https://discord.com/api/v10"
H = {"Authorization": f"Bot {TOKEN}", "User-Agent": "NovaBot-admin-role-test/1.0"}

results: list[tuple[bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((bool(ok), name))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("   -> " + str(extra)) if (extra and not ok) else ""))


def log_size() -> int:
    try:
        return os.path.getsize(LOG)
    except OSError:
        return 0


def wait_for_line(start_pos: int, expect: str, timeout: float = 5.0):
    """Sirf `expect` wali INSTANT line dhoondhta hai -> (local_time, line, pos)."""
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
            text = line.decode("utf-8", "replace")
            if expect not in text:
                continue  # kisi aur step ka line - aage badho
            m = re.match(rb"^\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})", line.strip())
            if not m:
                continue
            h, mi, s, ms = (int(x) for x in m.groups())
            return datetime.time(h, mi, s, ms * 1000), text.strip(), pos
        time.sleep(0.03)
    return None


def delta_ms(t0_epoch: float, log_time: datetime.time) -> float:
    now = datetime.datetime.fromtimestamp(t0_epoch)
    log_dt = datetime.datetime.combine(now.date(), log_time)
    return (log_dt - now).total_seconds() * 1000


def step(label: str, fn, must_contain: str, must_not: str | None = None):
    pos = log_size()
    t0 = time.time()
    resp = fn()
    if resp.status_code >= 400:
        check(f"{label}: API call", False, f"{resp.status_code} {resp.text[:160]}")
        return None
    found = wait_for_line(pos, must_contain, timeout=6.0)
    if found is None:
        check(f"{label}: INSTANT log line", False, f"6s mein '{must_contain}' wali line nahi aayi")
        return resp
    log_time, line, _ = found
    d = delta_ms(t0, log_time)
    print(f"        t0={datetime.datetime.fromtimestamp(t0):%H:%M:%S.%f}  "
          f"handler={log_time:%H:%M:%S.%f}  -> {d:.0f} ms")
    print(f"        {line}")
    check(f"{label}: line < 1000 ms (got {d:.0f} ms)", 0 <= d < 1000, f"{d:.0f} ms")
    check(f"{label}: detection sahi", must_contain in line, line)
    if must_not:
        check(f"{label}: '{must_not}' nahi hona chahiye", must_not not in line, line)
    check(f"{label}: member ban NAHI hua", b"protected" in line.encode() or b"chhoda" in line.encode(), line)
    return resp


def main() -> int:
    if not os.path.exists(LOG):
        print(f"FAIL: {LOG} nahi mila - bot running hai?")
        return 1

    print("Anti-Nuke INSTANT - ADMIN ROLE live test")
    print("Actor = bot (protected) -> koi member ban nahi hoga\n")

    # --- puraane bachche hue test channels saaf karo (galt endpoint se reh gaye the)
    for cid in ("1555837951035052072", "1555837956185395200"):
        r = requests.delete(f"{API}/channels/{cid}", headers=H, timeout=15)
        if r.status_code in (200, 204):
            print(f"  (cleanup: purana test channel {cid} delete hua)")
    # cleanup ke audit events ke log lines aa jayein, warna wo step 1 ki line ban jayenge
    time.sleep(2.0)

    role_id = None
    original_roles = None
    try:
        # 1) role create
        r = step(
            "role create",
            lambda: requests.post(f"{API}/guilds/{GID}/roles",
                                  headers=H, json={"name": ROLE_NAME, "permissions": "0"}, timeout=15),
            must_contain="role create by APEX",
        )
        if r is None or r.status_code >= 400:
            return 1
        role_id = r.json()["id"]

        # 2) role ko Administrator banaya (role_update detect)
        step(
            "role edit -> admin",
            lambda: requests.patch(f"{API}/guilds/{GID}/roles/{role_id}",
                                   headers=H, json={"permissions": str(ADMIN_BIT)}, timeout=15),
            must_contain="role edit (administrator) by APEX",
            must_not="admin nahi diya",
        )

        # bot ki current roles le lo (warna overwrite ho sakti hain)
        me = requests.get(f"{API}/guilds/{GID}/members/{BOT_ID}", headers=H, timeout=15).json()
        original_roles = me.get("roles", [])

        # 3) bot ko woh admin role di (member_role_update detect)
        step(
            "admin role mili (member_role_update)",
            lambda: requests.patch(f"{API}/guilds/{GID}/members/{BOT_ID}", headers=H,
                                   json={"roles": original_roles + [role_id]}, timeout=15),
            must_contain="admin role grant by APEX",
            must_not="admin nahi diya",
        )

        # 4) role wapas li (admin nahi diya -> skip)
        step(
            "role wapas li (normal)",
            lambda: requests.patch(f"{API}/guilds/{GID}/members/{BOT_ID}", headers=H,
                                   json={"roles": original_roles}, timeout=15),
            must_contain="admin nahi diya, chhoda",
        )

        # 5) role delete
        step(
            "role delete",
            lambda: requests.delete(f"{API}/guilds/{GID}/roles/{role_id}", headers=H, timeout=15),
            must_contain="role delete by APEX",
        )
    finally:
        # cleanup: role ho to hata do, bot ki roles wapas
        try:
            if original_roles is not None:
                requests.patch(f"{API}/guilds/{GID}/members/{BOT_ID}", headers=H,
                               json={"roles": original_roles}, timeout=15)
            if role_id:
                requests.delete(f"{API}/guilds/{GID}/roles/{role_id}", headers=H, timeout=15)
        except requests.RequestException:
            pass

    try:
        bans = requests.get(f"{API}/guilds/{GID}/bans", headers=H, timeout=15).json()
        check("koi accidental ban nahi hua (bans clean)", isinstance(bans, list) and len(bans) == 0, bans)
        roles = requests.get(f"{API}/guilds/{GID}/roles", headers=H, timeout=15).json()
        check("test role saaf ho gaya", all(r["name"] != ROLE_NAME for r in roles),
              [r["name"] for r in roles])
    except requests.RequestException as exc:
        check("cleanup verify", False, exc)

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
