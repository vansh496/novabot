"""Embed builder: /embed command se modal khulta hai, embed ban ke chala jata hai."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


def parse_color(raw: str, default: discord.Color = None) -> discord.Color:
    if default is None:
        default = discord.Color.blurple()
    text = str(raw or "").strip().lstrip("#")
    if not text:
        return default
    try:
        return discord.Color(int(text, 16))
    except ValueError:
        return default


def split_image_thumbnail(raw: str) -> tuple[str, str]:
    """`image` ya `image | thumbnail` (ya `| thumbnail`) ko do URL mein toda.

    Discord modal mein 5 field ka limit hai, isliye image + thumbnail
    ek hi field mein pipe se alag hote hain.
    """
    parts = [p.strip() for p in str(raw or "").strip().split("|", 1)]
    image = parts[0]
    thumbnail = parts[1] if len(parts) > 1 else ""
    return image, thumbnail


class EmbedModal(discord.ui.Modal, title="Embed Builder"):
    title_input = discord.ui.TextInput(
        label="Title",
        placeholder="Embed ka title",
        max_length=256,
        required=False,
    )
    description_input = discord.ui.TextInput(
        label="Description",
        placeholder="Main text (line breaks chalenge)",
        style=discord.TextStyle.paragraph,
        max_length=4000,
        required=False,
    )
    color_input = discord.ui.TextInput(
        label="Color (hex)",
        placeholder="#5865F2",
        default="#5865F2",
        max_length=7,
        required=False,
    )
    image_input = discord.ui.TextInput(
        label="Image / Thumbnail URL",
        placeholder="image URL  (dono ho to:  image | thumbnail)",
        required=False,
    )
    footer_input = discord.ui.TextInput(
        label="Footer text (optional)",
        placeholder="Footer...",
        max_length=2048,
        required=False,
    )

    def __init__(self, channel: discord.abc.Messageable = None) -> None:
        super().__init__()
        # Slash command mein jo channel diya gaya ho wahan bhejne ke liye
        self.channel_override = channel

    async def on_submit(self, interaction: discord.Interaction) -> None:
        title = str(self.title_input.value or "").strip()
        description = str(self.description_input.value or "").strip()
        if not title and not description:
            return await interaction.response.send_message(
                "Kam se kam Title ya Description to daalein.", ephemeral=True
            )

        embed = discord.Embed(
            title=title or None,
            description=description or None,
            color=parse_color(str(self.color_input.value or "")),
        )

        # Modal mein Discord 5 field ka limit deta hai, isliye dono ek hi field mein:
        #   "https://img.png"                    -> sirf image
        #   "https://img.png | https://t.png"     -> image + thumbnail (top-right chhota)
        #   "| https://t.png"                     -> sirf thumbnail
        image, thumbnail = split_image_thumbnail(str(self.image_input.value or ""))
        for setter, url in ((embed.set_image, image), (embed.set_thumbnail, thumbnail)):
            if not url:
                continue
            try:
                setter(url=url)
            except (ValueError, TypeError, discord.HTTPException):
                pass  # galt URL ho to woh part chhod do

        footer = str(self.footer_input.value or "").strip()
        if footer:
            embed.set_footer(text=footer)

        target = getattr(self, "channel_override", None) or interaction.channel

        # Pehle jawab, phir message (3 second ka limit hota hai)
        await interaction.response.send_message(f"✅ Embed bhej diya: {target.mention}", ephemeral=True)
        try:
            await target.send(embed=embed)
        except (discord.HTTPException, AttributeError):
            await interaction.followup.send(
                "❌ Embed nahi bhej saka (channel permissions check karein).", ephemeral=True
            )


class Embeds(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="embed", description="Modal se custom embed banayein aur bhejein")
    @app_commands.describe(channel="Embed kahan bhejna hai (default: yehi channel)")
    @app_commands.default_permissions(manage_messages=True)
    async def embed_cmd(self, interaction: discord.Interaction, channel: discord.TextChannel = None) -> None:
        # Channel ka naam modal ke saath store kar lete hain
        await interaction.response.send_modal(EmbedModal(channel))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Embeds(bot))
