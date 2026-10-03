"""Smoke test: bina Discord token ke saare modules check karta hai.

Chalane ka tareeqa (project root se):
    python tests/smoke_test.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

PASS = 0
FAIL = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {detail}")


# ---------------------------------------------------------------------------
# 1) Settings module
# ---------------------------------------------------------------------------


_SETTINGS_BACKUP = None


def test_settings() -> None:
    print("\n== settings.py ==")
    import settings

    # Pehle run ka data na dobe — purana file ka backup lo
    global _SETTINGS_BACKUP
    if os.path.exists(settings.SETTINGS_FILE):
        with open(settings.SETTINGS_FILE, "r", encoding="utf-8") as fh:
            _SETTINGS_BACKUP = fh.read()

    settings.ensure_file()

    # Purane test data ko saaf karo (pichhle run ka pollution)
    import json

    if os.path.exists(settings.SETTINGS_FILE):
        with open(settings.SETTINGS_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        changed = False
        for key in ("TEST_GUILD_1", "DASH_TEST"):
            if key in data:
                del data[key]
                changed = True
        if changed:
            with open(settings.SETTINGS_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
    check("settings file banti hai", os.path.exists(settings.SETTINGS_FILE))

    cfg = settings.get("TEST_GUILD_1")
    check("default settings milti hain", cfg["welcome"]["enabled"] is False)
    check("default anti-nuke OFF hai", cfg["antinuke"]["enabled"] is False)
    check("whitelist default list hai", cfg["antinuke"]["whitelist"] == [])

    # Save + live reload
    settings.set_section(
        "TEST_GUILD_1",
        "welcome",
        {"enabled": True, "channel_id": "123456", "message": "Hi {user}", "use_embed": "false"},
    )
    cfg2 = settings.get("TEST_GUILD_1")["welcome"]
    check("enabled save hua (True)", cfg2["enabled"] is True, str(cfg2.get("enabled")))
    check("channel_id int bana (123456)", cfg2["channel_id"] == 123456, str(cfg2.get("channel_id")))
    check("use_embed str se bool bana", cfg2["use_embed"] is False, str(cfg2.get("use_embed")))
    check("message save hua", cfg2["message"] == "Hi {user}")

    # Unknown key ignore honi chahiye
    settings.set_section("TEST_GUILD_1", "verification", {"enabled": True, "hack_field": "x"})
    v = settings.get("TEST_GUILD_1")["verification"]
    check("unknown field ignore hui", "hack_field" not in v and v["enabled"] is True)

    # Type coercion
    import settings as s

    check("bool coerce", s._coerce(True, "yes") is True)
    check("int coerce (galt value -> default)", s._coerce(5, "abc") == 5)
    check("list coerce (string -> list)", s._coerce([], "1, 2\n3") == ["1", "2", "3"])

    # File badalne par bot ko naye settings milti hain (mtime check)
    import json

    with open(settings.SETTINGS_FILE, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    check("JSON file mein guild data hai", "TEST_GUILD_1" in raw)

    # Invalid section
    try:
        settings.set_section("TEST_GUILD_1", "nope", {"a": 1})
        check("galat section raise karta hai", False)
    except KeyError:
        check("galat section raise karta hai", True)


# ---------------------------------------------------------------------------
# 2) Bot + cogs (bina token ke)
# ---------------------------------------------------------------------------


def test_bot_cogs() -> None:
    print("\n== bot.py + cogs ==")
    import discord
    from discord.ext import commands

    intents = discord.Intents.default()
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

    extensions = [
        "cogs.general",
        "cogs.welcome",
        "cogs.verification",
        "cogs.tickets",
        "cogs.antinuke",
        "cogs.embeds",
    ]

    async def run() -> None:
        loaded = []
        for ext in extensions:
            try:
                await bot.load_extension(ext)
                loaded.append(ext)
            except Exception as exc:  # noqa: BLE001
                check(f"load {ext}", False, repr(exc))
        check("saare 6 cogs load hue", len(loaded) == 6, f"sirf {len(loaded)}")

        # Bot login nahi karega, isliye anti-nuke polling loop abhi cancel karo
        pre = bot.get_cog("AntiNuke")
        if pre is not None:
            pre.poll_audit_logs.cancel()

        names = sorted(cmd.name for cmd in bot.tree.get_commands())
        expected = sorted(["ping", "help", "welcome", "verify", "ticket", "embed", "antinuke_status"])
        check("slash commands register hue", names == expected, f"mila: {names}")

        # Groups ke andar sub-commands
        groups = {c.name: c for c in bot.tree.get_commands() if hasattr(c, "commands")}
        for gname, subs in {
            "welcome": ["setup", "test", "dm-test", "leave-test"],
            "verify": ["setup", "panel"],
            "ticket": ["setup", "panel"],
        }.items():
            grp = groups.get(gname)
            got = sorted(sub.name for sub in getattr(grp, "commands", []))
            check(f"/{gname} ke sub-commands", got == sorted(subs), f"mila: {got}")

        # Persistent views (discord.py connection state ke view_store mein)
        store = getattr(bot._connection, "_view_store", None)
        ids = set()
        if store is not None:
            for items in store._views.values():
                for (_ctype, cid) in items.keys():
                    ids.add(cid)
        wanted = {
            "verify_button_v1",
            "ticket_open_v1",
            "ticket_close_v1",
            "ticket_reopen_v1",
            "ticket_delete_v1",
        }
        check("persistent views register hue", wanted.issubset(ids), f"missing: {wanted - ids}")

        # Helper functions
        from cogs.tickets import _sanitize
        from cogs.welcome import _format

        check("ticket name sanitize", _sanitize("Raiz#4444!") == "raiz-4444")
        class _M:
            mention = "<@1>"
            name = "u"
            display_name = "U"
            id = 1
        class _E:
            def __init__(self, name, id, animated=False):
                self.name = name
                self.id = id
                self.animated = animated

        class _G:
            name = "Server"
            member_count = 10
            emojis = [_E(name="fire", id=1555913518652334240, animated=True)]

        text = _format("Hi {user} to {server} #{member_count}", _M(), _G())
        check("welcome variables replace", text == "Hi <@1> to Server #10", text)
        text = _format("Naya update :fire: 5:30 baje", _M(), _G())
        check(
            "welcome shortcodes resolve hote hain",
            text == "Naya update <a:fire:1555913518652334240> 5:30 baje",
            text,
        )

        from cogs.antinuke import CATEGORY_BY_ACTION
        from discord import AuditLogAction

        check(
            "anti-nuke action map",
            CATEGORY_BY_ACTION.get(AuditLogAction.ban) == "bans"
            and CATEGORY_BY_ACTION.get(AuditLogAction.channel_delete) == "channels"
            and CATEGORY_BY_ACTION.get(AuditLogAction.bot_add) == "bots",
            CATEGORY_BY_ACTION,
        )
        check(
            "max_bots default (bot add fallback)",
            __import__("settings").default_settings()["antinuke"].get("max_bots") == 1,
        )

        cog = bot.get_cog("AntiNuke")
        if cog is not None:
            cog.poll_audit_logs.cancel()
        await bot.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# 3) Dashboard (Flask test client - bina login ke)
# ---------------------------------------------------------------------------


def test_dashboard() -> None:
    print("\n== dashboard/app.py ==")
    os.environ.setdefault("CLIENT_ID", "TEST_CLIENT_ID")
    os.environ.setdefault("CLIENT_SECRET", "TEST_CLIENT_SECRET")
    os.environ.setdefault("DISCORD_TOKEN", "")
    os.environ.setdefault("REDIRECT_URI", "http://localhost:5000/callback")

    spec = importlib.util.spec_from_file_location(
        "dashboard_app", os.path.join(ROOT, "dashboard", "app.py")
    )
    mod = importlib.util.module_from_spec(spec)
    # Flask ko root_path chahiye — module ko sys.modules mein register karo
    sys.modules["dashboard_app"] = mod
    try:
        spec.loader.exec_module(mod)
        check("Flask app import hua", True)
    except Exception as exc:  # noqa: BLE001
        check("Flask app import hua", False, repr(exc))
        return

    client = mod.app.test_client()

    resp = client.get("/")
    check("GET / landing page (200)", resp.status_code == 200, str(resp.status_code))

    resp = client.get("/servers")
    check("/servers bina login -> /login redirect", resp.status_code == 302)

    resp = client.get("/login")
    check("/login Discord par redirect karta hai", resp.status_code == 302)
    loc = resp.headers.get("Location", "")
    check(
        "login URL mein client_id + scope hai",
        "discord.com/oauth2/authorize" in loc and "client_id=TEST_CLIENT_ID" in loc and "guilds" in loc,
        loc[:120],
    )

    # CSRF protection
    resp = client.post("/api/123/welcome", json={"enabled": True})
    check("bina CSRF token -> 403", resp.status_code == 403, str(resp.status_code))

    # Galat state (OAuth callback)
    resp = client.get("/callback?state=galat&code=x")
    check("galat oauth state -> 400", resp.status_code == 400, str(resp.status_code))

    # Authenticated save flow (Discord API ko mock nahi - access 403 aana chahiye)
    with client.session_transaction() as sess:
        sess["csrf"] = "tok"
        sess["token"] = "fake_token"
    resp = client.post(
        "/api/123/welcome",
        json={"enabled": True},
        headers={"X-CSRF-Token": "tok"},
    )
    check(
        "fake login par access denied (403)",
        resp.status_code == 403,
        str(resp.status_code),
    )

    # Settings module direct save (yehi dashboard karta hai)
    import settings

    settings.set_section("DASH_TEST", "antinuke", {"enabled": True, "max_bans": 7, "instant_ban": False})
    cfg = settings.get("DASH_TEST")["antinuke"]
    check("dashboard-style save kaam karta hai", cfg["enabled"] is True and cfg["max_bans"] == 7)
    check("instant_ban toggle save hoti hai", cfg["instant_ban"] is False, cfg)

    # Template rendering (server page) - fake data ke saath
    with mod.app.test_request_context("/servers/1"), mod.app.app_context():
        html = mod.render_template(
            "server.html",
            guild={"id": "1", "name": "Test Server", "icon": "x"},
            channels=[{"id": "11", "name": "general"}],
            categories=[],
            roles=[{"id": "22", "name": "Staff"}],
            cfg=cfg and settings.get("DASH_TEST"),
            modules_on=1,
            bot_user={"id": "9", "username": "NovaBot", "avatar": None},
            bot_in=True,
            emojis=[{"id": "55", "name": "party", "animated": True}],
            invite="https://discord.com/oauth2/authorize?client_id=x",
        )
        check("server.html render hoti hai", "Anti-Nuke" in html and "tab-welcome" in html)
        check("settings JSON inject hoti hain", '"max_bans": 7' in html)
        check("antinuke tab mein instant_ban toggle hai", 'name="instant_ban"' in html)
        check("antinuke tab mein admin-role text hai", "Administrator wali role" in html)
        check("antinuke tab mein max_bots limit hai", 'name="max_bots"' in html)
        check("embed builder mein thumbnail field hai", 'id="emb-thumb"' in html)
        check("embed preview mein thumbnail box hai", 'id="de-thumb"' in html)
        check("server ke emojis inject hote hain", "window.EMOJIS" in html and '"name": "party"' in html)
        check("emoji fields marked hain (data-emoji)", html.count("data-emoji") >= 6, html.count("data-emoji"))

    # emoji list helper (animated pehle, ids string)
    sample = [
        {"id": 2, "name": "static_one", "animated": False},
        {"id": 1, "name": "boom", "animated": True},
        {"id": None, "name": "bad"},
        "junk",
    ]
    got = mod._emoji_list(sample)
    check(
        "emoji list: animated pehle + id string",
        [e["id"] for e in got] == ["1", "2"] and got[0]["animated"] is True,
        got,
    )
    check("emoji list: khaali/None safe", mod._emoji_list(None) == [] and mod._emoji_list([]) == [])

    js_path = os.path.join(ROOT, "dashboard", "static", "js", "script.js")
    with open(js_path, encoding="utf-8") as fh:
        js = fh.read()
    check(
        "JS emoji ko image mein dikhata hai",
        "cdn.discordapp.com/emojis" in js and "pv-emoji" in js and "&lt;(a?)" in js,
    )
    check("JS mein emoji picker hai", "initEmojiPickers" in js and "emoji-picker" in js and "emojiSyntax" in js)

    for tpl in ("base.html", "index.html", "servers.html", "message.html"):
        path = os.path.join(ROOT, "dashboard", "templates", tpl)
        check(f"template exist: {tpl}", os.path.exists(path))

    check("CSS file exist", os.path.exists(os.path.join(ROOT, "dashboard", "static", "css", "style.css")))
    check("JS file exist", os.path.exists(os.path.join(ROOT, "dashboard", "static", "js", "script.js")))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("NovaBot smoke test")
    print("=" * 50)
    test_settings()
    test_bot_cogs()
    test_dashboard()
    print("=" * 50)
    print(f"RESULT: {PASS} passed, {FAIL} failed")

    # Settings file ko test se pehle waisa hi chhod do
    try:
        import settings as _s

        if _SETTINGS_BACKUP is not None:
            with open(_s.SETTINGS_FILE, "w", encoding="utf-8") as fh:
                fh.write(_SETTINGS_BACKUP)
        elif os.path.exists(_s.SETTINGS_FILE):
            with open(_s.SETTINGS_FILE, "r", encoding="utf-8") as fh:
                data = __import__("json").load(fh)
            for key in ("TEST_GUILD_1", "DASH_TEST"):
                data.pop(key, None)
            with open(_s.SETTINGS_FILE, "w", encoding="utf-8") as fh:
                __import__("json").dump(data, fh, indent=2)
    except Exception:  # noqa: BLE001
        pass

    sys.exit(1 if FAIL else 0)
