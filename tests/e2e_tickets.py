"""E2E ticket test: open -> close -> reopen -> delete, REAL guild par.

CHALANE SE PEHLE:
    1. Bot band karo  ->  same token se do gateway session nahi ban sakte
    2. python tests/e2e_tickets.py
    3. Bot wapas chalu karo

Ye test asli server par ek ticket channel banata hai, band/kholta hai aur
akhir mein delete karta hai (transcript log message bhi hata deta hai).
Fake interaction banakar asli cogs ke callbacks call karte hain.
"""
import asyncio
import os
import sys
import traceback
from contextlib import suppress

ROOT = r"C:\Users\vansh\Desktop\Default Project"
sys.path.insert(0, ROOT)
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(os.path.join(ROOT, ".env"))

import discord

import settings
from cogs.tickets import TicketOpenView, TicketCloseView, TicketManageView

GID = 1554407195037401200
EXPECTED_CATEGORY = 1554407460406562937
SUPPORT_ROLE = 1554408048720740422
LOG_CHANNEL = 1554407793103212614

results = []


def check(name, cond, extra=""):
    results.append((bool(cond), name))
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (("   -> " + str(extra)) if (extra and not cond) else ""))


class FakeResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content=None, **kwargs):
        self.sent.append(str(content))

    async def defer(self, *args, **kwargs):
        pass


class FakeInteraction:
    def __init__(self, guild, user, channel=None):
        self.guild = guild
        self.guild_id = guild.id
        self.user = user
        self.channel = channel
        self.response = FakeResponse()


intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
ready = asyncio.Event()


@client.event
async def on_ready():
    ready.set()


async def run():
    cfg = settings.get(str(GID)).get("tickets", {})
    print("config: enabled=%s category=%s support=%s log=%s" % (
        cfg.get("enabled"), cfg.get("category_id"), cfg.get("support_role_id"), cfg.get("log_channel_id")))

    guild = client.get_guild(GID)
    if guild is None:
        print("  [FAIL] guild cache mein nahi mila")
        return
    print("guild: %s (channels=%d, members cached=%d)" % (guild.name, len(guild.channels), len(guild.members)))

    # Owner ko chhod kar koi regular member chuno - owner par overwrites lagte hi nahi
    # (Discord: guild owner hamesha sab permission rakhta hai).
    candidates = [m for m in guild.members
                  if m.id != guild.owner_id and not m.bot]
    if candidates:
        creator = candidates[0]
    else:
        creator = await guild.fetch_member(guild.owner_id)
    # Neeche poora flow pehle se `owner` naam se likha hai - ab woh test creator hai.
    owner = creator
    print("test user:", creator, "| is owner:", creator.id == guild.owner_id,
          "| admin:", creator.guild_permissions.administrator)

    # Purana open ticket rok sakta hai - pehle topic wale channels dikhao
    from cogs.tickets import _find_open_ticket, _creator_id
    open_before = await _find_open_ticket(guild, owner.id)
    print("pehle se open ticket:", open_before)
    check("test se pehle koi open ticket nahi", open_before is None, open_before)

    ticket = None
    try:
        # ---------------- 1. OPEN ----------------
        print("\n--- 1) OPEN TICKET ---")
        view = TicketOpenView()
        i1 = FakeInteraction(guild, owner)
        await view.children[0].callback(i1)
        print("   response:", i1.response.sent)

        ticket = await _find_open_ticket(guild, owner.id)
        check("ticket channel bana", ticket is not None)
        if ticket is None:
            return
        check("channel ka naam ticket-* hai", ticket.name.startswith("ticket-"), ticket.name)
        check("sahi category mein", ticket.category is not None and ticket.category.id == EXPECTED_CATEGORY,
              getattr(ticket.category, "id", None))
        check("topic mein creator id", str(owner.id) in (ticket.topic or ""), ticket.topic)
        ow = ticket.overwrites_for(guild.default_role)
        check("default role chhupa (private)", ow.view_channel is False, ow)
        check("creator ko dikhta", ticket.permissions_for(owner).view_channel is True)
        check("support role ko dikhta", ticket.permissions_for(guild.get_role(SUPPORT_ROLE)).view_channel is True)
        check("user ko jawab mila", any("Ticket ban gaya" in s for s in i1.response.sent), i1.response.sent)

        msgs = [m async for m in ticket.history(limit=5)]
        check("ticket mein welcome embed + close button aaya",
              any(m.embeds and m.embeds[0].title == "🎫 Ticket Opened" for m in msgs))
        check("close button ka custom_id sahi",
              any(any(c.custom_id == "ticket_close_v1" for row in m.components for c in row.children) for m in msgs))

        # ---------------- 2. CLOSE ----------------
        print("\n--- 2) CLOSE TICKET ---")
        v2 = TicketCloseView()
        i2 = FakeInteraction(guild, owner, channel=ticket)
        await v2.children[0].callback(i2)
        print("   response:", i2.response.sent)
        check("channel closed-* ho gaya", ticket.name.startswith("closed-"), ticket.name)
        check("user ko jawab mila", any("band kar diya" in s for s in i2.response.sent), i2.response.sent)
        # Note: admin/owner ko Discord hamesha sab permission deta hai (overwrites
        # bypass), isliye permissions_for sirf regular member par meaningful hai.
        if owner.id == guild.owner_id or owner.guild_permissions.administrator:
            print("  [SKIP] permissions_for check - test member admin/owner hai")
        else:
            check("creator ab channel nahi dekh sakta",
                  ticket.permissions_for(owner).view_channel is not True)
        check("close: overwrite mein view=False", ticket.overwrites_for(owner).view_channel is False,
              ticket.overwrites_for(owner).view_channel)
        msgs = [m async for m in ticket.history(limit=5)]
        check("reopen/delete buttons aaye",
              any(any(c.custom_id in ("ticket_reopen_v1", "ticket_delete_v1")
                      for row in m.components for c in row.children) for m in msgs))

        # ---------------- 3. REOPEN ----------------
        print("\n--- 3) REOPEN TICKET ---")
        v3 = TicketManageView()
        i3 = FakeInteraction(guild, owner, channel=ticket)
        await v3.children[0].callback(i3)   # reopen
        print("   response:", i3.response.sent)
        check("channel wapas ticket-*", ticket.name.startswith("ticket-"), ticket.name)
        check("creator wapas dekh sakta", ticket.permissions_for(owner).view_channel is True)

        # ---------------- 4. DELETE (+ transcript log) ----------------
        print("\n--- 4) DELETE TICKET ---")
        v4 = TicketManageView()
        i4 = FakeInteraction(guild, owner, channel=ticket)
        tid = ticket.id
        await v4.children[1].callback(i4)   # delete
        print("   response:", i4.response.sent)
        # GUILD_CHANNEL_DELETE event cache se hatane mein thoda lagta hai
        for _ in range(20):
            await asyncio.sleep(0.5)
            if client.get_guild(GID).get_channel(tid) is None:
                break
        check("channel delete ho gaya (cache)", client.get_guild(GID).get_channel(tid) is None)
        import requests as _rq
        resp = _rq.get(
            f"https://discord.com/api/v10/channels/{tid}",
            headers={"Authorization": f"Bot {os.getenv('DISCORD_TOKEN')}"},
            timeout=20,
        )
        check("channel delete ho gaya (REST 404)", resp.status_code == 404, resp.status_code)
        ticket = None

        log = guild.get_channel(LOG_CHANNEL)
        found = []
        if isinstance(log, discord.TextChannel):
            found = [m async for m in log.history(limit=5)]
        check("log channel mein transcript gaya",
              any(m.embeds and m.embeds[0].title == "📜 Ticket Transcript" for m in found))
        # test ka transcript message hata do
        for m in found:
            if m.embeds and m.embeds[0].title == "📜 Ticket Transcript" and m.author.bot:
                await m.delete()
                print("   (test transcript message delete kiya)")

    except Exception:
        traceback.print_exc()
        results.append((False, "exception: " + traceback.format_exc(limit=1).strip().splitlines()[-1]))


async def main():
    token = os.getenv("DISCORD_TOKEN")
    # client.start = login + gateway connect (login akela sirf REST auth karta hai)
    runner = asyncio.create_task(client.start(token), name="client-start")
    try:
        await asyncio.wait_for(ready.wait(), timeout=30)
    except (asyncio.TimeoutError, TimeoutError):
        print("gateway ready nahi hua (30s) - runner error:", runner.exception())
        return
    try:
        await run()
    finally:
        await client.close()
        with suppress(Exception):
            await asyncio.wait_for(runner, timeout=10)


if __name__ == "__main__":
    asyncio.run(main())
    print("\n" + "=" * 50)
    passed = sum(1 for ok, _ in results if ok)
    for ok, name in results:
        if not ok:
            print("  FAIL:", name)
    print("E2E RESULT: %d passed, %d failed" % (passed, len(results) - passed))
    sys.exit(0 if passed == len(results) else 1)
