"""Anti-Nuke system.

Do tareeke se kaam karta hai:

  A) INSTANT (1 second ke andar) - `on_audit_log_entry_create` gateway event:
     kisi ne bhi bot ADD kiya, member ko BAN/KICK kiya, CHANNEL ya ROLE
     banaya/deleted, kisi ko **Administrator wali role** de di / role edit
     karke admin bana liya, ya kisi **member ke role HATA diye** → attacker
     ko foran ban. Ismein ADMIN bhi nahi bachta (sirf server owner, bot
     owner, whitelist aur khud bot safe hain).

  B) Threshold (fallback) - har 2 second mein audit log poll: ek window ke
     andar limit se zyada bans/kicks/channels/roles → alert + config action.
"""

from __future__ import annotations

import datetime
import logging
import os
import time

import discord
from discord import AuditLogAction
from discord import app_commands
from discord.ext import commands, tasks

import settings

_log = logging.getLogger("antinuke")

# action -> category (category ka naam hi config key ban jata hai: max_bans, max_kicks...)
CATEGORY_BY_ACTION = {
    AuditLogAction.ban: "bans",
    AuditLogAction.kick: "kicks",
    AuditLogAction.bot_add: "bots",
    AuditLogAction.channel_create: "channels",
    AuditLogAction.channel_delete: "channels",
    AuditLogAction.role_create: "roles",
    AuditLogAction.role_delete: "roles",
}

# INSTANT: in mein se koi bhi hua to 1 second ke andar ban
INSTANT_ACTIONS = {
    AuditLogAction.bot_add: "bot add",
    AuditLogAction.ban: "member ban",
    AuditLogAction.kick: "member kick",
    AuditLogAction.channel_create: "channel create",
    AuditLogAction.channel_delete: "channel delete",
    AuditLogAction.role_create: "role create",
    AuditLogAction.role_delete: "role delete",
}

# In actions par tabhi ban, jab Administrator GRANT ki ja rahi ho.
# (Warna rozmarra ki normal role-editing par bhi ban lag jata.)
# Alag se: member_role_update par role HATE gaye ho to bhi instant ban hai
# (neeche `_special_label` dekhein).
ADMIN_ROLE_ACTIONS = {
    AuditLogAction.member_role_update: "admin role grant",
    AuditLogAction.role_update: "role edit (administrator)",
}

# Dono milakar listener ka gate banate hain
ALL_INSTANT_ACTIONS = set(INSTANT_ACTIONS) | set(ADMIN_ROLE_ACTIONS)


class AntiNuke(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # guild_id -> set of audit entry ids (jo already process ho chuki hain)
        self._seen: dict[str, set[int]] = {}
        # guild_id -> user_id -> category -> timestamps
        self._history: dict[str, dict[int, dict[str, list[float]]]] = {}
        self.poll_audit_logs.start()

    def cog_unload(self) -> None:
        self.poll_audit_logs.cancel()

    # ------------------------------------------------------------------
    # Audit log polling
    # ------------------------------------------------------------------

    @tasks.loop(seconds=2.0)
    async def poll_audit_logs(self) -> None:
        # Fallback: gateway event (`on_audit_log_entry_create`) miss ho jaye to
        for guild in list(self.bot.guilds):
            cfg = settings.get(guild.id).get("antinuke", {})
            if not cfg.get("enabled"):
                continue
            try:
                entries = [entry async for entry in guild.audit_logs(limit=25, oldest_first=False)]
            except Exception:
                continue  # permission nahi ya rate limit

            key = str(guild.id)
            seen = self._seen.setdefault(key, set())
            # naye -> purane, taake counting sahi ho
            for entry in reversed(entries):
                if entry.id in seen:
                    continue
                seen.add(entry.id)
                try:
                    await self._process_entry(guild, cfg, entry)
                except Exception:
                    pass  # ek entry fail ho to polling chalti rahe
            # set chhoti rakho
            if len(seen) > 150:
                self._seen[key] = set(sorted(seen)[-80:])

    @poll_audit_logs.before_loop
    async def before_poll(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    # INSTANT (gateway event -> 1 second ke andar)
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry) -> None:
        """Discord turant hi ye event bhejta hai - polling ka intezaar nahi."""
        guild = entry.guild
        if guild is None:
            return
        cfg = settings.get(guild.id).get("antinuke", {})
        if not cfg.get("enabled") or not cfg.get("instant_ban", True):
            return
        if entry.action not in ALL_INSTANT_ACTIONS:
            return  # inhe threshold poll (2s) ginne dega

        key = str(guild.id)
        seen = self._seen.setdefault(key, set())
        if entry.id in seen:
            return  # poll already process kar chuka
        seen.add(entry.id)
        if len(seen) > 150:
            self._seen[key] = set(sorted(seen)[-80:])

        try:
            await self._instant(guild, cfg, entry)
        except Exception:  # noqa: BLE001 - polling chalti rahe
            _log.exception("instant handler fail (entry=%s)", entry.id)

    @commands.Cog.listener()
    async def on_guild_delete(self, guild: discord.Guild) -> None:
        """Bot ko server se nikaal diya (kick/ban/remove) to owner ko turant khabar."""
        if getattr(guild, "unavailable", False):
            return  # sirf Discord outage tha
        await self._dm_owner(
            f"⚠️ Bot ko server se hata diya gaya: **{guild.name}** ({guild.id}).\n"
            f"Anti-Nuke wahan ab kaam nahi karega - check karein kaun tha."
        )

    def _protected(self, guild: discord.Guild, cfg: dict, user) -> bool:
        """Instant ban mein sirf ye log safe.

        Admin, moderator, doosre bots - SAB ban ho sakte hain (user ki demand).
        """
        if self.bot.user is not None and user.id == self.bot.user.id:
            return True
        if user.id == guild.owner_id:
            return True
        owner_env = (os.getenv("BOT_OWNER_ID") or "").strip()
        if owner_env and str(user.id) == owner_env:
            return True
        return str(user.id) in {str(x) for x in cfg.get("whitelist", [])}

    @staticmethod
    def _admin_role_granted(guild: discord.Guild, entry: discord.AuditLogEntry) -> bool:
        """Role ke zariye Administrator GRANT hui? (sirf wahi ban-worthy hai)

        Do tareeke:
          1) member_role_update: kisi member/bot ko admin wali role de di gayi
          2) role_update: role ki permission edit karke Administrator add kiya
        """
        after = entry.after
        before = entry.before

        # 1) kisi ko admin wali role di gayi ($add)
        added = getattr(after, "roles", None) or []
        for role in added:
            perms = getattr(role, "permissions", None)
            if perms is None:  # cache miss -> dobara dhoondho
                cached = guild.get_role(getattr(role, "id", 0))
                perms = getattr(cached, "permissions", None)
            if perms is not None and perms.administrator:
                return True

        # 2) role ki permission edit karke Administrator add kiya
        after_perms = getattr(after, "permissions", None)
        if after_perms is not None and after_perms.administrator:
            before_perms = getattr(before, "permissions", None)
            if before_perms is None or not before_perms.administrator:
                return True
        return False

    def _special_label(self, guild: discord.Guild, entry: discord.AuditLogEntry) -> str | None:
        """`ADMIN_ROLE_ACTIONS` wali entries ke liye instant-ban ka label.

        Do hi maamle ban-worthy hain:
          1) Administrator GRANT hui (purana logic)
          2) Kisi **member ke role HATE diye** (nayi demand) - chahe ek hi role
             ho, usko bhi nuker maana jayega.
        Warna None -> rozmarra ki normal role-editing, koi action nahi.
        """
        if entry.action not in ADMIN_ROLE_ACTIONS:
            return None
        if self._admin_role_granted(guild, entry):
            return ADMIN_ROLE_ACTIONS[entry.action]

        if entry.action == AuditLogAction.member_role_update:
            removed = self._removed_roles(entry)
            if removed:
                names = ", ".join(f"`{getattr(role, 'name', '?')}`" for role in removed[:4])
                extra = "" if len(removed) <= 4 else f" +{len(removed) - 4} aur"
                return f"member ke role hate ({names}{extra})"
            hint = "role add hue ya pata nahi chala"
        else:
            hint = "admin nahi diya"
        _log.info(
            "Anti-Nuke INSTANT: %s (%s) by %s -> %s, chhoda",
            ADMIN_ROLE_ACTIONS.get(entry.action),
            entry.action.name,
            entry.user_id,
            hint,
        )
        return None

    @staticmethod
    def _removed_roles(entry: discord.AuditLogEntry) -> list:
        """member_role_update mein kaun se role HATE gaye?

        Khaali list = ya to kuch hataya hi nahi, ya pata nahi chala (cache miss)
        - dono maamle mein hum andaza nahi lagate, warna galat banda ban ho jayega.
        """
        before = getattr(entry, "before", None)
        after = getattr(entry, "after", None)
        old = getattr(before, "roles", None)
        new = getattr(after, "roles", None)
        if old is None or new is None:
            changes = getattr(entry, "changes", None) or {}
            change = changes.get("roles")
            if change is not None:
                old, new = change.old, change.new
        if old is None or new is None:
            return []
        kept = {int(getattr(role, "id", 0) or 0) for role in new}
        return [role for role in old if int(getattr(role, "id", 0) or 0) not in kept]

    async def _instant(self, guild: discord.Guild, cfg: dict, entry: discord.AuditLogEntry) -> None:
        label = INSTANT_ACTIONS.get(entry.action)
        if label is None:
            label = self._special_label(guild, entry)
            if label is None:
                return  # normal role-editing - koi action nahi

        user = entry.user
        if user is None:
            # Member cache miss (naya ya hata hua member) - REST se turant laao
            uid = getattr(entry, "user_id", None)
            if not uid:
                return
            try:
                user = await self.bot.fetch_user(uid)
            except discord.HTTPException:
                _log.warning("Anti-Nuke: actor %s resolve nahi hua, chhoda", uid)
                return

        target_id = getattr(entry.target, "id", None)
        bot_id = self.bot.user.id if self.bot.user else None
        bot_attacked = (
            entry.action in (AuditLogAction.ban, AuditLogAction.kick) and target_id == bot_id
        )

        # Khud nuke karne wala (ya bot ko nikaalne wala) protected NAHI hai
        if not bot_attacked and self._protected(guild, cfg, user):
            _log.info("Anti-Nuke INSTANT: %s by %s (%s) -> protected, chhoda", label, user, user.id)
            return

        reason = f"Anti-Nuke INSTANT: {label} by {user} ({user.id})"
        start = time.monotonic()
        try:
            await guild.ban(user, reason=reason)
            result = "🔨 INSTANT BAN"
        except discord.HTTPException as exc:
            result = f"❌ ban fail (HTTP {exc.status})"
        except Exception as exc:  # noqa: BLE001
            result = f"❌ ban fail ({type(exc).__name__})"
        elapsed_ms = (time.monotonic() - start) * 1000

        _log.info(
            "Anti-Nuke INSTANT: %s by %s (%s) -> %s (ban API %.0f ms)",
            label, user, user.id, result, elapsed_ms,
        )

        if bot_attacked:
            title = (
                "🚨 BOT KO BAN KAR DIYA GAYA"
                if entry.action == AuditLogAction.ban
                else "🚨 BOT KO KICK KAR DIYA GAYA"
            )
            extra = (
                "\n⚠️ Bot ab khud server se nikal chuka hai. Agar ban lag gaya to theek, "
                "warna owner ko **turant** haath daalna chahiye."
            )
        elif result.startswith("🔨"):
            title = "⚡ Anti-Nuke: INSTANT BAN"
            extra = ""
        else:
            title = "🚨 Anti-Nuke: nuker mila, par ban fail"
            extra = "\nRole position / Manage Bans permission check karein."

        await self._alert(
            guild,
            cfg,
            title=title,
            description=(
                f"**Nuker:** {user.mention} (`{user.id}`)\n"
                f"**Action:** {label}\n"
                f"**Result:** {result}\n"
                f"**Reaction:** ban call {elapsed_ms:.0f} ms mein"
                f"{extra}"
            ),
            color=discord.Color.red(),
        )
        await self._dm_owner(
            f"⚡ Anti-Nuke ({guild.name} / {guild.id}): **{user}** ({user.id}) ne "
            f"'{label}' kiya -> {result}"
        )

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _whitelisted(self, guild: discord.Guild, cfg: dict, user: discord.abc.User) -> bool:
        if self.bot.user is not None and user.id == self.bot.user.id:
            return True
        if user.id == guild.owner_id:
            return True
        owner_env = (os.getenv("BOT_OWNER_ID") or "").strip()
        if owner_env and str(user.id) == owner_env:
            return True
        whitelist = {str(x) for x in cfg.get("whitelist", [])}
        if str(user.id) in whitelist:
            return True
        if cfg.get("ignore_bots", True) and getattr(user, "bot", False):
            return True
        if cfg.get("ignore_admins", True):
            perms = getattr(user, "guild_permissions", None)
            if perms is not None and (perms.administrator or perms.manage_guild):
                return True
        return False

    async def _process_entry(self, guild: discord.Guild, cfg: dict, entry: discord.AuditLogEntry) -> None:
        category = CATEGORY_BY_ACTION.get(entry.action)
        if category is None:
            return

        user = entry.user
        if user is None:
            return

        # --- Sabse pehle: agar BOT ko ban kar diya gaya hai to foran alert ---
        target_id = getattr(entry.target, "id", None)
        if entry.action == AuditLogAction.ban and self.bot.user is not None and target_id == self.bot.user.id:
            await self._alert(
                guild,
                cfg,
                title="🚨 BOT KO BAN KAR DIYA GAYA",
                description=f"**{user}** ne bot ko ban kar diya!\n"
                f"Anti-nuke ab kaam nahi kar payega. Owner turant check karein.",
                color=discord.Color.red(),
            )
            await self._dm_owner(
                f"⚠️ Guild **{guild.name}** ({guild.id}): **{user}** ({user.id}) ne bot ko ban kar diya."
            )
            return

        if self._whitelisted(guild, cfg, user):
            return

        now = time.time()
        window = max(10, int(cfg.get("window_seconds") or 60))

        # Purani entry par action MAT lo. Nahi to bot restart hote hi uske aakhri
        # 25 audit entries dobara gin jaati hain aur kisi ke ghanton pehle ke
        # ek channel delete par foran ban chala jata tha (false positive).
        created = getattr(entry, "created_at", None)
        if created is not None:
            age = (discord.utils.utcnow() - created).total_seconds()
            if age > window:
                return

        per_user = self._history.setdefault(str(guild.id), {}).setdefault(user.id, {})
        bucket = per_user.setdefault(category, [])
        bucket[:] = [stamp for stamp in bucket if now - stamp <= window]
        bucket.append(now)

        threshold = int(cfg.get(f"max_{category}") or 0)
        if threshold <= 0 or len(bucket) < threshold:
            return

        # Threshold cross ho gayi -> action
        action = str(cfg.get("action") or "none").lower()
        count = len(bucket)
        taken = "⚠️ sirf alert (action OFF)"

        if user.id != guild.owner_id:
            if action == "ban":
                try:
                    await guild.ban(
                        user,
                        reason=f"Anti-Nuke: {count}x {category} in {window}s (threshold {threshold})",
                    )
                    taken = "🔨 BANNED"
                except discord.HTTPException:
                    taken = "❌ ban fail (permissions/role position check karein)"
            elif action == "kick":
                try:
                    await guild.kick(
                        user,
                        reason=f"Anti-Nuke: {count}x {category} in {window}s (threshold {threshold})",
                    )
                    taken = "👢 KICKED"
                except discord.HTTPException:
                    taken = "❌ kick fail (permissions/role position check karein)"
            else:
                taken = "⚠️ sirf alert (action OFF)"
        else:
            taken = "⚠️ server owner par action nahi liya (sirf alert)"

        # Count reset - warna har audit entry par dobara trigger hoga
        bucket.clear()

        await self._alert(
            guild,
            cfg,
            title="💣 Anti-Nuke Alert",
            description=(
                f"**Moderator:** {user.mention} (`{user.id}`)\n"
                f"**Action:** {category.upper()}\n"
                f"**Count:** {count} bar {window}s ke andar (limit {threshold})\n"
                f"**Result:** {taken}"
            ),
            color=discord.Color.red(),
        )

    async def _alert(
        self,
        guild: discord.Guild,
        cfg: dict,
        title: str,
        description: str,
        color: discord.Color,
    ) -> None:
        channel_id = int(cfg.get("alert_channel_id") or 0)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _dm_owner(self, text: str) -> None:
        owner_id = (os.getenv("BOT_OWNER_ID") or "").strip()
        if not owner_id:
            return
        try:
            user = await self.bot.fetch_user(int(owner_id))
            await user.send(text)
        except (discord.HTTPException, ValueError):
            pass

    # ------------------------------------------------------------------
    # Command
    # ------------------------------------------------------------------

    @app_commands.command(name="antinuke_status", description="Anti-Nuke ki current settings dikhayein")
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        cfg = settings.get(interaction.guild_id)["antinuke"]
        channel = interaction.guild.get_channel(int(cfg.get("alert_channel_id") or 0))
        embed = discord.Embed(
            title="💣 Anti-Nuke Status",
            color=discord.Color.red() if cfg.get("enabled") else discord.Color.greyple(),
        )
        embed.add_field(name="Enabled", value="✅ Haan" if cfg.get("enabled") else "❌ Nahi", inline=True)
        embed.add_field(
            name="Instant ban (1 sec)",
            value="⚡ Haan" if cfg.get("instant_ban", True) else "❌ Nahi",
            inline=True,
        )
        embed.add_field(name="Action", value=str(cfg.get("action", "none")).upper(), inline=True)
        embed.add_field(name="Window", value=f"{cfg.get('window_seconds')}s", inline=True)
        embed.add_field(name="Max bans", value=str(cfg.get("max_bans")), inline=True)
        embed.add_field(name="Max kicks", value=str(cfg.get("max_kicks")), inline=True)
        embed.add_field(name="Max bots", value=str(cfg.get("max_bots")), inline=True)
        embed.add_field(name="Max channels", value=str(cfg.get("max_channels")), inline=True)
        embed.add_field(name="Max roles", value=str(cfg.get("max_roles")), inline=True)
        embed.add_field(name="Alert channel", value=channel.mention if channel else "set nahi", inline=True)
        embed.add_field(
            name="Whitelist",
            value=", ".join(f"`{x}`" for x in cfg.get("whitelist", [])) or "koi nahi",
            inline=False,
        )
        embed.add_field(
            name="Instant actions",
            value=", ".join(
                f"`{v}`" for v in sorted(set(INSTANT_ACTIONS.values()) | set(ADMIN_ROLE_ACTIONS.values()))
            )
            + ", `member ke role hatana`",
            inline=False,
        )
        embed.add_field(
            name="Note",
            value="Saari settings dashboard se badli ja sakti hain. "
            "Instant ban par admin/mod/bot bhi nahi bachta (sirf owner + whitelist safe).",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AntiNuke(bot))
