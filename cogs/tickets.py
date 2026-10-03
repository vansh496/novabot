"""Ticket system: panel -> private ticket channel -> close / reopen / delete."""

from __future__ import annotations

import io
import re

import discord
from discord import app_commands
from discord.ext import commands

import emoji_codes
import settings

INVALID_CHARS = re.compile(r"[^a-z0-9_\-]+")


def _color(raw: str, default: discord.Color = None) -> discord.Color:
    if default is None:
        default = discord.Color.blurple()
    text = str(raw or "").strip().lstrip("#")
    if not text:
        return default
    try:
        return discord.Color(int(text, 16))
    except ValueError:
        return default


def _sanitize(name: str) -> str:
    cleaned = INVALID_CHARS.sub("-", name.lower()).strip("-")
    return (cleaned or "user")[:80]


def _creator_id(channel: discord.abc.GuildChannel) -> int:
    match = re.search(r"Ticket by (\d+)", getattr(channel, "topic", "") or "")
    return int(match.group(1)) if match else 0


def _is_support(interaction: discord.Interaction) -> bool:
    cfg = settings.get(interaction.guild_id).get("tickets", {})
    user = interaction.user
    if isinstance(user, discord.Member):
        if user.guild_permissions.administrator or user.guild_permissions.manage_guild:
            return True
        role = interaction.guild.get_role(int(cfg.get("support_role_id") or 0))
        if role is not None and role in user.roles:
            return True
    return False


async def _find_open_ticket(guild: discord.Guild, user_id: int) -> discord.TextChannel | None:
    for channel in guild.text_channels:
        if _creator_id(channel) == user_id and not channel.name.startswith("closed-"):
            return channel
    return None


# --------------------------------------------------------------------------
# Views (persistent - custom_id wajah se restart ke baad bhi kaam karte hain)
# --------------------------------------------------------------------------


class TicketOpenView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open Ticket",
        style=discord.ButtonStyle.primary,
        emoji="🎫",
        custom_id="ticket_open_v1",
    )
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None:
            return await interaction.response.send_message("Server ke andar use karein.", ephemeral=True)

        cfg = settings.get(interaction.guild_id).get("tickets", {})
        if not cfg.get("enabled"):
            return await interaction.response.send_message(
                "Tickets abhi band hain. Admin pehle `/ticket setup` chalaye.", ephemeral=True
            )

        existing = await _find_open_ticket(interaction.guild, interaction.user.id)
        if existing is not None:
            return await interaction.response.send_message(
                f"⚠️ Aapke paas pehle se open ticket hai: {existing.mention}", ephemeral=True
            )

        guild = interaction.guild
        # Note: Guild mein get_category() nahi hota - get_channel + isinstance check
        category = guild.get_channel(int(cfg.get("category_id") or 0))
        if not isinstance(category, discord.CategoryChannel):
            category = None
        support = guild.get_role(int(cfg.get("support_role_id") or 0))

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True,
            ),
        }
        if support is not None:
            overwrites[support] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True,
                manage_messages=True,
            )

        name = "ticket-" + _sanitize(getattr(interaction.user, "name", "user"))
        try:
            channel = await guild.create_text_channel(
                name,
                category=category,
                overwrites=overwrites,
                topic=f"Ticket by {interaction.user.id}",
                reason=f"Ticket opened by {interaction.user}",
            )
        except discord.HTTPException:
            return await interaction.response.send_message(
                "❌ Ticket channel nahi ban saka (permissions check karein).", ephemeral=True
            )

        embed = discord.Embed(
            title="🎫 Ticket Opened",
            description=emoji_codes.resolve(cfg.get("message"), interaction.guild.emojis)
            or "Support team jaldi is ticket mein jawab dega.",
            color=_color(cfg.get("embed_color")),
        )
        embed.add_field(name="Opened by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Ticket ID", value=f"`{channel.id}`", inline=True)
        embed.set_footer(text="Ticket band karne ke liye neeche ka button use karein")

        try:
            await channel.send(
                content=support.mention if support else None,
                embed=embed,
                view=TicketCloseView(),
            )
        except discord.HTTPException:
            pass

        await interaction.response.send_message(f"🎫 Ticket ban gaya: {channel.mention}", ephemeral=True)


class TicketCloseView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        emoji="🔒",
        custom_id="ticket_close_v1",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Ye button sirf ticket mein kaam karta hai.", ephemeral=True)

        cfg = settings.get(interaction.guild_id).get("tickets", {})
        channel = interaction.channel
        creator_id = _creator_id(channel)

        if creator_id != interaction.user.id and not _is_support(interaction):
            return await interaction.response.send_message(
                "Sirf ticket creator ya support team close kar sakti hai.", ephemeral=True
            )

        # Creator ke liye channel band
        # Note: get_member() sirf cache dekhta hai (members chunk na hue to None)
        # - isliye cache miss par REST se fetch kar lete hain.
        creator = interaction.guild.get_member(creator_id)
        if creator is None:
            try:
                creator = await interaction.guild.fetch_member(creator_id)
            except discord.HTTPException:
                creator = None
        if creator is not None:
            try:
                await channel.set_permissions(creator, view_channel=False)
            except discord.HTTPException:
                pass

        new_name = channel.name if channel.name.startswith("closed-") else ("closed-" + channel.name)[:100]
        try:
            await channel.edit(name=new_name, reason=f"Ticket closed by {interaction.user}")
        except discord.HTTPException:
            pass

        embed = discord.Embed(
            title="🔒 Ticket Closed",
            description="Ye ticket band ho gayi hai.\n"
            "- **Reopen** - phir se khol do\n"
            "- **Delete** - hamesha ke liye delete (transcript log mein save hoga)",
            color=discord.Color.red(),
        )
        embed.set_footer(text=f"Closed by {interaction.user}")
        await channel.send(embed=embed, view=TicketManageView())

        # Log channel
        log_id = int(cfg.get("log_channel_id") or 0)
        log_channel = interaction.guild.get_channel(log_id) if log_id else None
        if isinstance(log_channel, discord.TextChannel):
            log_embed = discord.Embed(
                title="🎫 Ticket Closed",
                description=f"{channel.mention} closed by {interaction.user.mention}",
                color=discord.Color.orange(),
            )
            try:
                await log_channel.send(embed=log_embed)
            except discord.HTTPException:
                pass

        await interaction.response.send_message("🔒 Ticket band kar diya.", ephemeral=True)


class TicketManageView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Reopen",
        style=discord.ButtonStyle.success,
        emoji="🔓",
        custom_id="ticket_reopen_v1",
    )
    async def reopen_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Ye button sirf ticket mein kaam karta hai.", ephemeral=True)

        cfg = settings.get(interaction.guild_id).get("tickets", {})
        channel = interaction.channel
        creator_id = _creator_id(channel)

        if creator_id != interaction.user.id and not _is_support(interaction):
            return await interaction.response.send_message(
                "Sirf ticket creator ya support team reopen kar sakti hai.", ephemeral=True
            )

        creator = interaction.guild.get_member(creator_id)
        if creator is None:
            try:
                creator = await interaction.guild.fetch_member(creator_id)
            except discord.HTTPException:
                creator = None
        if creator is not None:
            try:
                await channel.set_permissions(
                    creator,
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                )
            except discord.HTTPException:
                pass

        if channel.name.startswith("closed-"):
            try:
                await channel.edit(name=channel.name[7:], reason=f"Ticket reopened by {interaction.user}")
            except discord.HTTPException:
                pass

        embed = discord.Embed(
            title="🔓 Ticket Reopened",
            description="Ye ticket phir se open hai. Support team jaldi jawab degi.",
            color=discord.Color.green(),
        )
        embed.set_footer(text=f"Reopened by {interaction.user}")
        await channel.send(embed=embed, view=TicketCloseView())
        await interaction.response.send_message("🔓 Ticket reopen kar diya.", ephemeral=True)

    @discord.ui.button(
        label="Delete",
        style=discord.ButtonStyle.danger,
        emoji="🗑️",
        custom_id="ticket_delete_v1",
    )
    async def delete_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Ye button sirf ticket mein kaam karta hai.", ephemeral=True)

        if not _is_support(interaction):
            return await interaction.response.send_message(
                "Ticket delete sirf support team kar sakti hai.", ephemeral=True
            )

        cfg = settings.get(interaction.guild_id).get("tickets", {})
        channel = interaction.channel

        # Pehle jawab do, phir channel delete karo
        await interaction.response.send_message("🗑️ Ticket delete ho raha hai...", ephemeral=True)

        # Transcript log channel mein
        log_id = int(cfg.get("log_channel_id") or 0)
        log_channel = interaction.guild.get_channel(log_id) if log_id else None
        if isinstance(log_channel, discord.TextChannel):
            try:
                lines = []
                async for message in channel.history(limit=100):
                    stamp = message.created_at.strftime("%Y-%m-%d %H:%M")
                    lines.append(f"[{stamp}] {message.author}: {message.content or '(attachment/embed)'}")
                lines.reverse()
                transcript = "\n".join(lines) or "(koi message nahi)"
                file = discord.File(
                    io.BytesIO(transcript.encode("utf-8")),
                    filename=f"transcript-{channel.name}.txt",
                )
                embed = discord.Embed(
                    title="📜 Ticket Transcript",
                    description=f"{channel.name} - deleted by {interaction.user.mention}",
                    color=discord.Color.red(),
                )
                await log_channel.send(embed=embed, file=file)
            except discord.HTTPException:
                pass

        try:
            await channel.delete(reason=f"Ticket deleted by {interaction.user}")
        except discord.HTTPException:
            pass


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ticket = app_commands.Group(name="ticket", description="Ticket system settings")

    @ticket.command(name="setup", description="Ticket system set karein")
    @app_commands.describe(
        category="Jahan ticket channels banenge (optional)",
        support_role="Support staff role",
        log_channel="Close/delete ki log yahan aayegi (optional)",
        message="Panel ka message (optional)",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def setup_cmd(
        self,
        interaction: discord.Interaction,
        support_role: discord.Role,
        category: discord.CategoryChannel = None,
        log_channel: discord.TextChannel = None,
        message: str = None,
    ) -> None:
        data = dict(settings.get_section(interaction.guild_id, "tickets"))
        data["enabled"] = True
        data["support_role_id"] = support_role.id
        if category is not None:
            data["category_id"] = category.id
        if log_channel is not None:
            data["log_channel_id"] = log_channel.id
        if message:
            data["message"] = message
        settings.set_section(interaction.guild_id, "tickets", data)
        await interaction.response.send_message(
            f"✅ Ticket system ON (support: {support_role.mention}).\n"
            f"Panel bhejne ke liye: `/ticket panel`",
            ephemeral=True,
        )

    @ticket.command(name="panel", description="Ticket panel bhejein")
    @app_commands.describe(channel="Panel bhejne ka channel (default: yehi channel)")
    @app_commands.default_permissions(manage_guild=True)
    async def panel_cmd(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel = None,
    ) -> None:
        cfg = settings.get(interaction.guild_id)["tickets"]
        channel = channel or interaction.channel

        # Panel channel yaad rakho (dashboard par bhi dikhta hai)
        data = dict(settings.get_section(interaction.guild_id, "tickets"))
        data["panel_channel_id"] = channel.id
        settings.set_section(interaction.guild_id, "tickets", data)

        embed = discord.Embed(
            title="🎫 Support Tickets",
            description=emoji_codes.resolve(cfg.get("message"), interaction.guild.emojis)
            or "Need help? Open a ticket below.",
            color=_color(cfg.get("embed_color")),
        )
        embed.set_footer(text="Ek waqt mein ek hi ticket khuli ho sakti hai")

        await channel.send(embed=embed, view=TicketOpenView())
        await interaction.response.send_message(f"✅ Panel bhej diya: {channel.mention}", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    bot.add_view(TicketOpenView())
    bot.add_view(TicketCloseView())
    bot.add_view(TicketManageView())
    await bot.add_cog(Tickets(bot))
