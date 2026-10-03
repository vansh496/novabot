"""General commands: /ping aur /help"""

from __future__ import annotations

import os

import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Bot ka latency check karein")
    async def ping(self, interaction: discord.Interaction) -> None:
        ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"🏓 Pong! `{ms}ms`")

    @app_commands.command(name="help", description="Saare commands aur features dekhein")
    async def help_cmd(self, interaction: discord.Interaction) -> None:
        dashboard = os.getenv("DASHBOARD_URL", "http://localhost:5000")
        embed = discord.Embed(
            title="📚 Commands & Features",
            description="Saari settings dashboard se hoti hain.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="🎫 Tickets",
            value="`/ticket setup` - category, support role, log channel set karein\n`/ticket panel` - panel bhejein",
            inline=False,
        )
        embed.add_field(
            name="👋 Welcome / Leave / Join DM",
            value="`/welcome setup` - welcome channel set karein\n"
            "`/welcome test` - sample welcome bhejein\n"
            "`/welcome dm-test` - sample join DM khud dekhein\n"
            "`/welcome leave-test` - sample leave message bhejein",
            inline=False,
        )
        embed.add_field(
            name="🛡️ Verification",
            value="`/verify setup` - verify channel + role set karein\n`/verify panel` - verify panel bhejein",
            inline=False,
        )
        embed.add_field(
            name="💣 Anti-Nuke",
            value="Ye dashboard se control hota hai (server -> Anti-Nuke).",
            inline=False,
        )
        embed.add_field(name="📨 Embed", value="`/embed` - modal se embed banayein aur bhejein", inline=False)
        embed.add_field(name="🌐 Dashboard", value=f"[{dashboard}]({dashboard})", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
