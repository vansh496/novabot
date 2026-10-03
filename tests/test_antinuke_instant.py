"""Anti-Nuke INSTANT logic test.

Koi real member ban nahi hota - sab fake objects + mock guild.ban.
Ye verify karta hai ki:
  * admin/mod/bot par bhi instant ban lagta hai (user ki demand)
  * kisi ko Administrator wali role dene (ya role edit se admin banane) par
    instant ban - normal/non-admin role dene par nahi
  * server owner / whitelist / khud bot safe hain
  * bot ko ban-kick karne wale par bhi ban ki koshish hoti hai
  * ban call 1 second ke andar ho jati hai
  * gateway listener entry ko theek mark karta hai (double-processing nahi)
"""
from __future__ import annotations

import asyncio
import datetime
import os
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import discord  # noqa: E402
from discord import AuditLogAction  # noqa: E402

import cogs.antinuke as antinuke_mod  # noqa: E402
from cogs.antinuke import INSTANT_ACTIONS, AntiNuke  # noqa: E402

results = []


def check(name: str, ok: bool, extra="") -> None:
    results.append((bool(ok), name))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (("   -> " + str(extra)) if (extra and not ok) else ""))


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

BOT_ID = 999_999_999_001
OWNER_ID = 111_111_111_001
ADMIN_ID = 222_222_222_001
TRUSTED_ID = 333_333_333_001


class FakeUser:
    def __init__(self, user_id: int, *, bot: bool = False, admin: bool = False, name: str = "user"):
        self.id = user_id
        self.bot = bot
        self.name = name
        self.discriminator = "0"
        self.guild_permissions = types.SimpleNamespace(administrator=admin, manage_guild=admin)

    def __str__(self) -> str:
        return self.name

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"


class FakeGuild:
    def __init__(self) -> None:
        self.id = 42
        self.name = "Test Guild"
        self.owner_id = OWNER_ID
        self.banned = []
        self.fail_with = None

    async def ban(self, user, *, reason: str | None = None, **kwargs) -> None:
        if self.fail_with is not None:
            response = types.SimpleNamespace(status=self.fail_with, reason="fake", headers={})
            raise discord.HTTPException(response, "fake error")
        self.banned.append((getattr(user, "id", user), reason))


def entry_for(action, user, *, target=None, entry_id: int = 1):
    return types.SimpleNamespace(
        action=action,
        user=user,
        target=target,
        id=entry_id,
        user_id=getattr(user, "id", None),
        guild=FakeGuild(),
    )


def make_cog() -> AntiNuke:
    # __init__ se task loop start hota - yahan sirf logic test karni hai
    cog = AntiNuke.__new__(AntiNuke)
    cog.bot = types.SimpleNamespace(user=types.SimpleNamespace(id=BOT_ID), guilds=[])
    cog._seen = {}
    cog._history = {}
    cog.alerts = []
    cog.dms = []

    async def _alert(guild, cfg, title, description, color):
        cog.alerts.append(f"{title} :: {description}")

    async def _dm(text: str) -> None:
        cog.dms.append(text)

    cog._alert = _alert
    cog._dm_owner = _dm
    return cog


CFG = {
    "enabled": True,
    "instant_ban": True,
    "whitelist": [str(TRUSTED_ID)],
    "action": "ban",
    "window_seconds": 60,
    "max_bans": 3,
    "max_kicks": 5,
    "max_channels": 5,
    "max_roles": 3,
    "ignore_admins": True,   # instant par iska koi asar NAHI hona chahiye
    "ignore_bots": True,     # instant par iska koi asar NAHI hona chahiye
}


async def run() -> None:
    admin = FakeUser(ADMIN_ID, admin=True, name="admin_guy")
    trusted = FakeUser(TRUSTED_ID, name="trusted_guy")
    owner = FakeUser(OWNER_ID, admin=True, name="server_owner")
    bot_user = FakeUser(BOT_ID, bot=True, name="APEX")

    # ------------------------------------------------------------------
    print("--- INSTANT: kiske saath ban lagta hai ---")
    instant_cases = [
        (AuditLogAction.bot_add, "bot add"),
        (AuditLogAction.ban, "member ban"),
        (AuditLogAction.kick, "member kick"),
        (AuditLogAction.channel_create, "channel create"),
        (AuditLogAction.channel_delete, "channel delete"),
        (AuditLogAction.role_create, "role create"),
        (AuditLogAction.role_delete, "role delete"),
    ]
    for action, label in instant_cases:
        cog = make_cog()
        guild = FakeGuild()
        e = entry_for(action, admin, entry_id=10)
        e.guild = guild
        start = time.monotonic()
        await cog._instant(guild, CFG, e)
        took_ms = (time.monotonic() - start) * 1000
        check(f"admin par '{label}' -> INSTANT BAN", len(guild.banned) == 1, guild.banned)
        check(f"'{label}' ban call < 1000 ms", took_ms < 1000, f"{took_ms:.0f} ms")
        check(f"'{label}' alert gaya", any("INSTANT BAN" in a for a in cog.alerts), cog.alerts)
        check(f"'{label}' owner ko DM gaya", len(cog.dms) == 1, cog.dms)

    # ------------------------------------------------------------------
    print("\n--- PROTECTED: in par ban NAHI lagna chahiye ---")
    for who, label in ((owner, "server owner"), (trusted, "whitelist user"), (bot_user, "khud bot")):
        cog = make_cog()
        guild = FakeGuild()
        e = entry_for(AuditLogAction.channel_delete, who, entry_id=2)
        e.guild = guild
        await cog._instant(guild, CFG, e)
        check(f"{label} safe rahe", guild.banned == [], guild.banned)
        check(f"{label}: koi alert nahi", cog.alerts == [], cog.alerts)

    # ------------------------------------------------------------------
    print("\n--- ADMIN ROLE -> INSTANT BAN (kisi ko bhi, bot ya member) ---")
    admin_role = types.SimpleNamespace(
        id=777, name="Admin", permissions=types.SimpleNamespace(administrator=True)
    )
    normal_role = types.SimpleNamespace(
        id=778, name="Member", permissions=types.SimpleNamespace(administrator=False)
    )

    def role_entry(entry_id, action, actor, added=(), before_p=None, after_p=None):
        e = entry_for(action, actor, entry_id=entry_id)
        before_kwargs, after_kwargs = {}, {}
        if added is not None:
            before_kwargs["roles"] = []
            after_kwargs["roles"] = list(added)
        if before_p is not None:
            before_kwargs["permissions"] = types.SimpleNamespace(administrator=before_p)
        if after_p is not None:
            after_kwargs["permissions"] = types.SimpleNamespace(administrator=after_p)
        e.before = types.SimpleNamespace(**before_kwargs)
        e.after = types.SimpleNamespace(**after_kwargs)
        return e

    # 1) kisi member/bot ko admin wali role de di -> ban
    cog, guild = make_cog(), FakeGuild()
    e = role_entry(301, AuditLogAction.member_role_update, admin, added=[admin_role])
    e.guild = guild
    await cog._instant(guild, CFG, e)
    check("kisi ko admin role dene par INSTANT BAN", len(guild.banned) == 1, guild.banned)
    check("alert mein 'admin role grant' label", any("admin role grant" in a for a in cog.alerts), cog.alerts)

    # 2) normal (non-admin) role dene par kuch nahi
    cog, guild = make_cog(), FakeGuild()
    e = role_entry(302, AuditLogAction.member_role_update, admin, added=[normal_role])
    e.guild = guild
    await cog._instant(guild, CFG, e)
    check("normal role dene par koi ban nahi", guild.banned == [], guild.banned)
    check("normal role par koi alert nahi", cog.alerts == [], cog.alerts)

    # 3) role edit karke Administrator add kiya -> ban
    cog, guild = make_cog(), FakeGuild()
    e = role_entry(303, AuditLogAction.role_update, admin, added=None,
                   before_p=False, after_p=True)
    e.guild = guild
    await cog._instant(guild, CFG, e)
    check("role edit se admin banane par INSTANT BAN", len(guild.banned) == 1, guild.banned)
    check("label 'role edit (administrator)'", any("role edit" in a for a in cog.alerts), cog.alerts)

    # 4) admin role ka sirf color change -> kuch nahi (galat ban nahi)
    cog, guild = make_cog(), FakeGuild()
    e = entry_for(AuditLogAction.role_update, admin, entry_id=304)
    e.guild = guild
    e.before = types.SimpleNamespace(color=0x000000)
    e.after = types.SimpleNamespace(color=0xFF0000)
    await cog._instant(guild, CFG, e)
    check("admin role ka color change -> koi ban nahi", guild.banned == [], guild.banned)

    # 5) admin permission REMOVE ki -> kuch nahi
    cog, guild = make_cog(), FakeGuild()
    e = role_entry(305, AuditLogAction.role_update, admin, added=None,
                   before_p=True, after_p=False)
    e.guild = guild
    await cog._instant(guild, CFG, e)
    check("admin hata par koi ban nahi", guild.banned == [], guild.banned)

    # 6) pehle se admin role thi, bas doosri permission edit -> kuch nahi
    cog, guild = make_cog(), FakeGuild()
    e = role_entry(306, AuditLogAction.role_update, admin, added=None,
                   before_p=True, after_p=True)
    e.guild = guild
    await cog._instant(guild, CFG, e)
    check("purani admin role ki edit -> koi ban nahi", guild.banned == [], guild.banned)

    # 7) khud server owner admin role de -> wo protected hai
    cog, guild = make_cog(), FakeGuild()
    e = role_entry(307, AuditLogAction.member_role_update, owner, added=[admin_role])
    e.guild = guild
    await cog._instant(guild, CFG, e)
    check("owner admin role de to khud safe", guild.banned == [], guild.banned)

    # ------------------------------------------------------------------
    print("\n--- BOT KO BAN / KICK kiya ---")
    for action, word in ((AuditLogAction.ban, "BAN"), (AuditLogAction.kick, "KICK")):
        cog = make_cog()
        guild = FakeGuild()
        e = entry_for(action, admin, target=types.SimpleNamespace(id=BOT_ID), entry_id=3)
        e.guild = guild
        await cog._instant(guild, CFG, e)
        check(f"bot ko {word} karne wale par ban ki koshish", len(guild.banned) == 1, guild.banned)
        check(f"bot {word} wala alert title", any(word in a for a in cog.alerts), cog.alerts)

    # ------------------------------------------------------------------
    print("\n--- ban fail (HTTP 403) handling ---")
    cog = make_cog()
    guild = FakeGuild()
    guild.fail_with = 403
    e = entry_for(AuditLogAction.channel_create, admin, entry_id=4)
    e.guild = guild
    await cog._instant(guild, CFG, e)
    check("HTTP 403 par crash nahi hota", True)
    check("fail hone par bhi alert gaya", any("fail" in a.lower() for a in cog.alerts), cog.alerts)

    # ------------------------------------------------------------------
    print("\n--- THRESHOLD path: purani entry par boot-time ban nahi ---")
    # Bot restart par poll aakhri 25 entries dobara ginta hai - ghanton purani
    # entry par ban chal jana = false positive (aja kal hua tha).
    stale_cfg = {**CFG, "max_channels": 1, "window_seconds": 10}
    regular = FakeUser(555_555_555_001, name="regular_guy")  # na admin, na whitelist

    cog = make_cog()
    guild = FakeGuild()
    e = entry_for(AuditLogAction.channel_delete, regular, entry_id=201)
    e.guild = guild
    e.created_at = discord.utils.utcnow()
    await cog._process_entry(guild, stale_cfg, e)
    check("fresh entry par threshold ban hua", len(guild.banned) == 1, guild.banned)

    cog = make_cog()
    guild = FakeGuild()
    e = entry_for(AuditLogAction.channel_delete, regular, entry_id=202)
    e.guild = guild
    e.created_at = discord.utils.utcnow() - datetime.timedelta(hours=3)
    await cog._process_entry(guild, stale_cfg, e)
    check("3 ghante purani entry par koi ban nahi", guild.banned == [], guild.banned)
    check("purani entry par koi alert nahi", cog.alerts == [], cog.alerts)

    # bot add: gateway event miss ho jaye to threshold fallback bhi ban kare
    bot_cfg = {**CFG, "max_bots": 1, "window_seconds": 10}
    cog, guild = make_cog(), FakeGuild()
    e = entry_for(AuditLogAction.bot_add, regular, entry_id=203)
    e.guild = guild
    e.created_at = discord.utils.utcnow()
    await cog._process_entry(guild, bot_cfg, e)
    check("bot add -> threshold fallback ne bhi ban kiya", len(guild.banned) == 1, guild.banned)
    check("bot add alert mein category bots", any("BOTS" in a for a in cog.alerts), cog.alerts)

    cog, guild = make_cog(), FakeGuild()
    e = entry_for(AuditLogAction.bot_add, owner, entry_id=204)
    e.guild = guild
    e.created_at = discord.utils.utcnow()
    await cog._process_entry(guild, bot_cfg, e)
    check("server owner bot add kare -> safe", guild.banned == [], guild.banned)

    # ------------------------------------------------------------------
    print("\n--- Embed modal: image | thumbnail split ---")
    from cogs.embeds import split_image_thumbnail

    check("sirf image", split_image_thumbnail("https://x/a.png") == ("https://x/a.png", ""))
    check(
        "image + thumbnail",
        split_image_thumbnail("https://x/a.png | https://x/t.png")
        == ("https://x/a.png", "https://x/t.png"),
    )
    check("sirf thumbnail", split_image_thumbnail("| https://x/t.png") == ("", "https://x/t.png"))
    check("khaali", split_image_thumbnail("") == ("", ""))

    # ------------------------------------------------------------------
    print("\n--- Gateway listener (seen marking + switches) ---")
    original_get = antinuke_mod.settings.get
    try:
        # 1) instant ON -> handled + marked
        antinuke_mod.settings.get = lambda gid: {"antinuke": dict(CFG)}
        cog = make_cog()
        guild = FakeGuild()
        e = entry_for(AuditLogAction.bot_add, admin, entry_id=101)
        e.guild = guild
        await cog.on_audit_log_entry_create(e)
        check("listener ne entry mark ki (poll dobara na kare)", 101 in cog._seen.get("42", set()),
              cog._seen)
        check("listener ne ban karwaya", len(guild.banned) == 1, guild.banned)

        # 2) non-instant -> seen MAT mark (threshold poll ko chalne do)
        cog = make_cog()
        guild = FakeGuild()
        e = entry_for(AuditLogAction.member_update, admin, entry_id=102)
        e.guild = guild
        await cog.on_audit_log_entry_create(e)
        check("non-instant entry threshold ke liye chhodi",
              102 not in cog._seen.get("42", set()), cog._seen)

        # 3) instant_ban OFF
        antinuke_mod.settings.get = lambda gid: {"antinuke": {**CFG, "instant_ban": False}}
        cog = make_cog()
        guild = FakeGuild()
        e = entry_for(AuditLogAction.channel_delete, admin, entry_id=103)
        e.guild = guild
        await cog.on_audit_log_entry_create(e)
        check("instant_ban OFF par koi action nahi",
              guild.banned == [] and cog.alerts == [], (guild.banned, cog.alerts))

        # 4) pura antinuke OFF
        antinuke_mod.settings.get = lambda gid: {"antinuke": {**CFG, "enabled": False}}
        cog = make_cog()
        guild = FakeGuild()
        e = entry_for(AuditLogAction.channel_delete, admin, entry_id=104)
        e.guild = guild
        await cog.on_audit_log_entry_create(e)
        check("antinuke OFF par koi action nahi",
              guild.banned == [] and cog.alerts == [], (guild.banned, cog.alerts))
    finally:
        antinuke_mod.settings.get = original_get


def main() -> int:
    print("Anti-Nuke INSTANT logic test (sab mock - koi real ban nahi)")
    print("INSTANT_ACTIONS:", ", ".join(sorted(set(INSTANT_ACTIONS.values()))))
    print()
    asyncio.run(run())
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
