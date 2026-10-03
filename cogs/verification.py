"""Verification system: button dabao -> role mil jaye."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import emoji_codes
import settings


class VerifyView(discord.ui.View):
    def __init__(self) -> None:
        # timeout=None + custom_id = persistent view (bot restart hone par bhi kaam karegi)
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.success,
        emoji="✅",
        custom_id="verify_button_v1",
    )
    async def verify(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("Server ke andar use karein.", ephemeral=True)

        cfg = settings.get(interaction.guild_id).get("verification", {})
        if not cfg.get("enabled"):
            return await interaction.response.send_message(
                "Verification abhi enabled nahi hai.", ephemeral=True
            )

        role = interaction.guild.get_role(int(cfg.get("role_id") or 0))
        if role is None:
            return await interaction.response.send_message(
                "Verify role set nahi hai. Admin pehle `/verify setup` chalaye.", ephemeral=True
            )

        if isinstance(interaction.user, discord.Member) and role in interaction.user.roles:
            return await interaction.response.send_message("Aap already verified ho ✅", ephemeral=True)

        try:
            await interaction.user.add_roles(role, reason="Verification completed")
        except discord.HTTPException:
            return await interaction.response.send_message(
                "❌ Role nahi mil saka (bot ke role ki position check karein).", ephemeral=True
            )

        await interaction.response.send_message("✅ Verified! Ab aapko access mil gaya hai.", ephemeral=True)


class Verify(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    verify = app_commands.Group(name="verify", description="Verification system settings")

    @verify.command(name="setup", description="Verify channel aur role set karein")
    @app_commands.describe(
        channel="Jahan verify panel aana chahiye",
        role="Verify hone par milne wali role",
        message="Panel ka message (optional)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        role: discord.Role,
        message: str = None,
    ) -> None:
        data = dict(settings.get_section(interaction.guild_id, "verification"))
        data["enabled"] = True
        data["channel_id"] = channel.id
        data["role_id"] = role.id
        if message:
            data["message"] = message
        settings.set_section(interaction.guild_id, "verification", data)
        await interaction.response.send_message(
            f"✅ Verification set: {channel.mention} -> {role.mention}\n"
            f"Panel bhejne ke liye: `/verify panel`",
            ephemeral=True,
        )

    @verify.command(name="panel", description="Verify panel bhejein")
    @app_commands.describe(channel="Panel bhejne ka channel (default: yehi channel)")
    @app_commands.default_permissions(manage_guild=True)
    async def panel_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
    ) -> None:
        cfg = settings.get(interaction.guild_id)["verification"]
        role = interaction.guild.get_role(int(cfg.get("role_id") or 0))
        if not cfg.get("enabled") or role is None:
            return await interaction.response.send_message(
                "Pehle `/verify setup` chalayein.", ephemeral=True
            )

        channel = channel or interaction.channel

        # Panel channel yaad rakho (dashboard par bhi dikhta hai)
        data = dict(settings.get_section(interaction.guild_id, "verification"))
        data["channel_id"] = channel.id
        settings.set_section(interaction.guild_id, "verification", data)

        color_raw = str(cfg.get("embed_color") or "#5865F2").lstrip("#")
        try:
            color = discord.Color(int(color_raw, 16))
        except ValueError:
            color = discord.Color.blurple()

        embed = discord.Embed(
            title="🛡️ Verification",
            description=emoji_codes.resolve(cfg.get("message"), interaction.guild.emojis)
            or "Click the button below to verify.",
            color=color,
        )
        embed.set_footer(text="Neeche diya gaya button dabayein")

        await channel.send(embed=embed, view=VerifyView())
        await interaction.response.send_message(f"✅ Panel bhej diya: {channel.mention}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    # Persistent view register - taake purane panel ke buttons bhi chalte rahein
    bot.add_view(VerifyView())
    await bot.add_cog(Verify(bot))
