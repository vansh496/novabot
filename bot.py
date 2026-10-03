"""Main Discord bot entry point.

Chalane ka tareeqa:  python bot.py
"""

from __future__ import annotations

import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

import settings

load_dotenv()

TOKEN = (os.getenv("DISCORD_TOKEN") or "").strip()

# Server Members Intent ON karna zaroori hai (welcome / leave / verification ke liye)
intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

EXTENSIONS = [
    "cogs.general",
    "cogs.welcome",
    "cogs.verification",
    "cogs.tickets",
    "cogs.antinuke",
    "cogs.embeds",
]

_commands_synced = False


async def setup_hook() -> None:
    # discord.py login ke waqt `self.setup_hook()` call karta hai —
    # isliye function ko bot par assign karna zaroori hai.
    for ext in EXTENSIONS:
        await bot.load_extension(ext)
    print(f"Loaded {len(EXTENSIONS)} cogs")


bot.setup_hook = setup_hook


async def _sync_commands() -> None:
    """Slash commands register karein (sirf ek baar, failure par dobara try)."""
    global _commands_synced
    if _commands_synced:
        return
    try:
        synced = await bot.tree.sync()
        _commands_synced = True
        print(f"Slash commands synced: {len(synced)}")
    except Exception as exc:  # noqa: BLE001 - next ready par dobara try hoga
        print(f"Command sync fail (dobara try hoga): {exc}")


@bot.event
async def on_ready() -> None:
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print(f"Connected to {len(bot.guilds)} server(s).")
    await _sync_commands()
    print("Bot ready. Dashboard chalane ke liye: python dashboard/app.py")


def main() -> None:
    if not TOKEN:
        raise SystemExit(
            "DISCORD_TOKEN nahi mila.\n"
            "1) .env.example ko copy karke .env naam se save karein\n"
            "2) .env mein token daalein\n"
            "3) Dobara `python bot.py` chalayein"
        )
    # Anti-Nuke ke instant-ban reactions ko ms tak measure kar sakein isliye
    # timestamp ke saath log chahiye.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s.%(msecs)03d %(levelname)-5s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    settings.ensure_file()
    # log_handler=None: discord.py apna alag handler na lagaye - warna har line
    # do bar print hoti hai (humara root handler + discord ka library handler).
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
