"""Welcome message, Leave message aur Join DM."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import settings


def _format(template: str, member: discord.Member, guild: discord.Guild) -> str:
    if not template:
        return ""
    return (
        str(template)
        .replace("{user}", member.mention)
        .replace("{username}", member.name)
        .replace("{display_name}", member.display_name)
        .replace("{server}", guild.name)
        .replace("{member_count}", str(guild.member_count))
        .replace("{id}", str(member.id))
    )


def _color(raw, default: discord.Color | None = None) -> discord.Color:
    """Dashboard se aaya hex color (#RRGGBB) -> discord.Color."""
    try:
        return discord.Color(int(str(raw or "").strip().lstrip("#"), 16))
    except ValueError:
        return default or discord.Color.green()


class Welcome(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    welcome = app_commands.Group(
        name="welcome",
        description="Welcome, Leave aur Join-DM settings",
    )

    # ---------------- events ----------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        cfg = settings.get(member.guild.id).get("welcome", {})

        # 1) Join DM (member ko seedha DM)
        if cfg.get("dm_enabled"):
            text = _format(cfg.get("dm_message", ""), member, member.guild)
            if text:
                try:
                    await member.send(text)
                except discord.HTTPException:
                    pass  # user ne DM band rakhe ho to chhod do

        # 2) Welcome channel
        if cfg.get("enabled"):
            channel = member.guild.get_channel(int(cfg.get("channel_id") or 0))
            if isinstance(channel, discord.TextChannel):
                text = _format(cfg.get("message", ""), member, member.guild)
                try:
                    if cfg.get("use_embed", True):
                        embed = discord.Embed(
                            title=f"Welcome {member.display_name}!",
                            description=text or None,
                            color=_color(cfg.get("embed_color")),
                        )
                        embed.set_thumbnail(url=member.display_avatar.url)
                        embed.set_footer(text=f"Member #{member.guild.member_count}")
                        await channel.send(embed=embed)
                    else:
                        await channel.send(text or member.mention)
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        cfg = settings.get(member.guild.id).get("welcome", {})
        if not cfg.get("leave_enabled"):
            return
        channel = member.guild.get_channel(int(cfg.get("leave_channel_id") or 0))
        if not isinstance(channel, discord.TextChannel):
            return
        text = _format(cfg.get("leave_message", ""), member, member.guild)
        try:
            await channel.send(text or f"{member.name} left.")
        except discord.HTTPException:
            pass

    # ---------------- commands ----------------

    @welcome.command(name="setup", description="Welcome system set karein")
    @app_commands.describe(channel="Jahan welcome aana chahiye", message="Custom message (optional)")
    @app_commands.default_permissions(manage_guild=True)
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        message: str = None,
    ) -> None:
        data = dict(settings.get_section(interaction.guild_id, "welcome"))
        data["enabled"] = True
        data["channel_id"] = channel.id
        if message:
            data["message"] = message
        settings.set_section(interaction.guild_id, "welcome", data)
        await interaction.response.send_message(
            f"✅ Welcome enabled in {channel.mention}.\n"
            f"Test karne ke liye: `/welcome test`",
            ephemeral=True,
        )

    @welcome.command(name="test", description="Sample welcome message bhejein")
    @app_commands.describe(channel="Test message kahan bhejna hai")
    @app_commands.default_permissions(manage_guild=True)
    async def test_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
    ) -> None:
        channel = channel or interaction.channel
        cfg = settings.get(interaction.guild_id)["welcome"]
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None:
            await interaction.response.send_message("Server ke andar chalayein.", ephemeral=True)
            return
        text = _format(cfg.get("message", ""), member, interaction.guild)
        if cfg.get("use_embed", True):
            embed = discord.Embed(
                title=f"Welcome {member.display_name}!",
                description=text or None,
                color=_color(cfg.get("embed_color")),
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.set_footer(text=f"Member #{interaction.guild.member_count}")
            await channel.send(embed=embed)
        else:
            await channel.send(text or member.mention)
        await interaction.response.send_message(f"✅ Test bhej diya: {channel.mention}", ephemeral=True)

    @welcome.command(name="dm-test", description="Sample join DM khud check karein")
    async def dm_test_cmd(self, interaction: discord.Interaction) -> None:
        cfg = settings.get(interaction.guild_id)["welcome"]
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None:
            await interaction.response.send_message("Server ke andar chalayein.", ephemeral=True)
            return
        text = _format(cfg.get("dm_message", ""), member, interaction.guild)
        try:
            await member.send(text or "Welcome!")
        except discord.HTTPException:
            await interaction.response.send_message("❌ Aapke DMs band hain, message nahi gaya.", ephemeral=True)
            return
        await interaction.response.send_message("✅ Join DM aapke DMs mein bhej diya.", ephemeral=True)

    @welcome.command(name="leave-test", description="Sample leave message bhejein")
    @app_commands.describe(channel="Test message kahan bhejna hai")
    @app_commands.default_permissions(manage_guild=True)
    async def leave_test_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
    ) -> None:
        channel = channel or interaction.channel
        cfg = settings.get(interaction.guild_id)["welcome"]
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None:
            await interaction.response.send_message("Server ke andar chalayein.", ephemeral=True)
            return
        text = _format(cfg.get("leave_message", ""), member, interaction.guild)
        await channel.send(text or f"{member.name} left.")
        await interaction.response.send_message(f"✅ Test bhej diya: {channel.mention}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
