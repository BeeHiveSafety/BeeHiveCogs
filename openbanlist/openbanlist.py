from redbot.core import commands, Config  # type: ignore
import discord
import aiohttp
import asyncio
from collections import Counter
from datetime import datetime, timedelta

TIMEOUT_DURATION = 28 * 24 * 60 * 60  # 28 days in seconds (max Discord timeout)

class OpenBanList(commands.Cog):
    """
    OpenBanlist is a project aimed at cataloging malicious Discord users and working to keep them out of servers in a united fashion.

    For more information or to report a user, please visit [openbanlist.cc](<https://openbanlist.cc>)
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "enabled": True,
            # Default actions for each severity: 1=high, 2=medium, 3=low
            "actions": {
                "1": "ban",
                "2": "kick",
                "3": "timeout"
            },
            "log_channel": None  # Default log channel is None
        }
        self.config.register_guild(**default_guild)
        self.banlist_url = "https://openbanlist.cc/data/banlist.json"
        self.session = aiohttp.ClientSession()
        self.bot.loop.create_task(self.update_banlist_periodically())
        self.timeout_task = self.bot.loop.create_task(self.timeout_enforcer())

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())
        if hasattr(self, "timeout_task"):
            self.timeout_task.cancel()

    @commands.guild_only()
    @commands.group(invoke_without_command=True)
    async def banlist(self, ctx):
        """
        OpenBanlist is a project aimed at cataloging malicious Discord users and working to keep them out of servers in a united fashion.

        For more information or to report a user, please visit [openbanlist.cc](<https://openbanlist.cc>)
        """
        await ctx.send_help(ctx.command)

    @commands.admin_or_permissions(manage_guild=True)
    @banlist.command()
    async def enable(self, ctx):
        """Enable the global banlist protection."""
        await self.config.guild(ctx.guild).enabled.set(True)
        embed = discord.Embed(
            title="Banlist enabled",
            description="Global banlist protection has been enabled.",
            color=0x2bbd8e
        )
        await ctx.send(embed=embed)

    @commands.admin_or_permissions(manage_guild=True)
    @banlist.command()
    async def disable(self, ctx):
        """Disable the global banlist protection."""
        await self.config.guild(ctx.guild).enabled.set(False)
        embed = discord.Embed(
            title="Banlist disabled",
            description="Global banlist protection has been disabled.",
            color=0xff4545
        )
        await ctx.send(embed=embed)

    @commands.admin_or_permissions(manage_guild=True)
    @banlist.group(name="action", invoke_without_command=True)
    async def action(self, ctx):
        """Show the current actions for each ban severity."""
        actions = await self.config.guild(ctx.guild).actions()
        severity_map = {"1": "High", "2": "Medium", "3": "Low"}
        valid_actions = ["kick", "ban", "timeout", "none"]
        embed = discord.Embed(
            title="OpenBanlist actions by severity",
            color=0x2bbd8e
        )
        for sev in ("1", "2", "3"):
            action = actions.get(sev, "none")
            embed.add_field(name=f"Severity {sev} ({severity_map[sev]})", value=action, inline=False)
        embed.set_footer(text="To set: banlist action set <severity> <action>")
        await ctx.send(embed=embed)

    @commands.admin_or_permissions(manage_guild=True)
    @action.command(name="set")
    async def action_set(self, ctx, severity: str, action: str):
        """
        Set the action to take for a given ban severity.
        Severity: 1 (high), 2 (medium), 3 (low)
        Action: kick, ban, timeout, or none
        """
        valid_severities = ["1", "2", "3"]
        valid_actions = ["kick", "ban", "timeout", "none"]
        if severity not in valid_severities:
            embed = discord.Embed(
                title="Invalid severity",
                description="Severity must be 1 (high), 2 (medium), or 3 (low).",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return
        if action not in valid_actions:
            embed = discord.Embed(
                title="Invalid action",
                description=f"Invalid action. Choose from: {', '.join(valid_actions)}",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return
        actions = await self.config.guild(ctx.guild).actions()
        actions[severity] = action
        await self.config.guild(ctx.guild).actions.set(actions)
        severity_map = {"1": "High", "2": "Medium", "3": "Low"}
        embed = discord.Embed(
            title="OpenBanlist action set",
            description=f"Action for severity {severity} ({severity_map[severity]}) set to: {action}",
            color=0x2bbd8e
        )
        await ctx.send(embed=embed)

    @commands.admin_or_permissions(manage_guild=True)
    @banlist.command()
    async def logs(self, ctx, channel: discord.TextChannel):
        """Set the logging channel for banlist actions."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        embed = discord.Embed(
            title="Logs configured",
            description=f"Logging channel set to {channel.mention}.",
            color=0x2bbd8e
        )
        await ctx.send(embed=embed)

    @banlist.command()
    async def check(self, ctx, user: discord.User = None):
        """Check if a user is on the global banlist."""
        if user is None:
            user_id = ctx.author.id
        else:
            user_id = user.id

        async with self.session.get(self.banlist_url) as response:
            if response.status == 200:
                banlist_data = await response.json()
                # Find all bans for this user by reported_id
                user_bans = []
                banlist_items = list(banlist_data.items())
                for idx, (ban_key, ban_info) in enumerate(banlist_items, 1):
                    if int(ban_info.get("reported_id", 0)) == user_id:
                        user_bans.append((idx, ban_info))
                if not user_bans:
                    embed = discord.Embed(
                        title="OpenBanlist check",
                        description=f"That user has no active bans or historical punishments on OpenBanlist.",
                        color=0x2bbd8e
                    )
                    await ctx.send(embed=embed)
                    return

                # Only consider bans that are still active (appeal_verdict is not "accepted")
                active_bans = [ban_info for idx, ban_info in user_bans if ban_info.get("appeal_info", {}).get("appeal_verdict", "").lower() != "accepted"]

                # If there are active bans, show the first one
                if active_bans:
                    active_ban = active_bans[0]
                    severity = str(active_ban.get("severity", "3"))
                    severity_map = {"1": "High", "2": "Medium", "3": "Low"}
                    embed = discord.Embed(
                        title="OpenBanlist check",
                        description=f"> Uh oh! <@{user_id}> is listed in the **[OpenBanlist](https://openbanlist.cc)**",
                        color=0xff4545
                    )
                    embed.add_field(name="Banned for", value=active_ban.get("ban_reason", "No reason provided yet, check back soon"), inline=True)
                    embed.add_field(name="Context", value=active_ban.get("context", "No context provided"), inline=False)
                    embed.add_field(name="Severity", value=f"{severity} ({severity_map.get(severity, 'Unknown')})", inline=True)
                    # Process reporter name if available
                    reporter_id = active_ban.get('reporter_id', 'Unknown')
                    reporter_name = active_ban.get('reporter_name', None)
                    if reporter_name:
                        reporter_display = f"{reporter_name} (<@{reporter_id}>)\n`{reporter_id}`"
                    else:
                        reporter_display = f"<@{reporter_id}>\n`{reporter_id}`"
                    embed.add_field(name="Reported by", value=reporter_display, inline=True)
                    # Process approver name if available
                    approver_id = active_ban.get('approver_id', 'Unknown')
                    approver_name = active_ban.get('approver_name', None)
                    if approver_name:
                        approver_display = f"{approver_name} (<@{approver_id}>)\n`{approver_id}`"
                    else:
                        approver_display = f"<@{approver_id}>\n`{approver_id}`"
                    embed.add_field(name="Approved by", value=approver_display, inline=True)
                    appealable_status = ":white_check_mark: **Yes**" if active_ban.get("appealable", False) else ":x: **Not eligible**"
                    embed.add_field(name="Can be appealed?", value=appealable_status, inline=True)
                    if active_ban.get("appealed", False):
                        appeal_info = active_ban.get("appeal_info", {})
                        appeal_verdict = appeal_info.get("appeal_verdict", "")
                        if not appeal_verdict:
                            appeal_status = "Pending"
                        elif appeal_verdict == "accepted":
                            # If the appeal is accepted, this ban should not be considered active, so skip showing as active
                            # Instead, fall through to the else block below
                            active_bans = []
                        elif appeal_verdict == "denied":
                            appeal_status = "Denied"
                        else:
                            appeal_status = "Unknown"
                        if active_bans:
                            embed.add_field(name="Appeal status", value=appeal_status, inline=True)
                            embed.add_field(name="Appeal verdict", value=appeal_verdict or "No verdict provided", inline=False)
                            appeal_reason = appeal_info.get("appeal_reason", "")
                            if appeal_reason:
                                embed.add_field(name="Appeal reason", value=appeal_reason, inline=False)
                    if active_bans:
                        evidence = active_ban.get("evidence", "")
                        if evidence:
                            embed.set_image(url=evidence)
                        report_date = active_ban.get("report_date", "Unknown")
                        ban_date = active_ban.get("ban_date", "Unknown")
                        if report_date != "Unknown":
                            embed.add_field(name="Reported on", value=f"<t:{report_date}:f>", inline=True)
                        else:
                            embed.add_field(name="Report date", value="Unknown", inline=True)
                        if ban_date != "Unknown":
                            embed.add_field(name="Added to database", value=f"<t:{ban_date}:f>", inline=True)
                        else:
                            embed.add_field(name="Ban date", value="Unknown", inline=True)
                        await ctx.send(embed=embed)
                        return  # Only send the active ban embed if still valid

                # If we get here, either there are no active bans, or the only ban(s) have an accepted appeal
                embed = discord.Embed(
                    title="OpenBanlist check",
                    description=f"<@{user_id}> is **not currently banned** but has a punishment history on **[OpenBanlist](https://openbanlist.cc)**",
                    color=discord.Color.orange()
                )
                # Add a single field for prior bans as per instructions
                prior_bans_lines = []
                for idx, ban_info in user_bans:
                    reason = ban_info.get("ban_reason", "No reason provided")
                    ban_date = ban_info.get("ban_date", None)
                    severity = str(ban_info.get("severity", "3"))
                    severity_map = {"1": "High", "2": "Medium", "3": "Low"}
                    if ban_date and ban_date != "Unknown":
                        try:
                            # Discord dynamic timestamp
                            date_str = f"<t:{int(ban_date)}:f>"
                        except Exception:
                            date_str = str(ban_date)
                    else:
                        date_str = "Unknown"
                    prior_bans_lines.append(f"`#{idx}` for **{reason}** `({severity_map.get(severity, 'Unknown')})` on **{date_str}**")
                if prior_bans_lines:
                    embed.add_field(
                        name="Prior bans",
                        value="\n".join(prior_bans_lines),
                        inline=False
                    )
                await ctx.send(embed=embed)

    @banlist.command()
    async def stats(self, ctx):
        """Show statistics about the banlist."""
        async with self.session.get(self.banlist_url) as response:
            if response.status == 200:
                banlist_data = await response.json()
                total_banned = len(banlist_data)
                ban_reasons = [ban_info.get("ban_reason", "No reason provided") for ban_info in banlist_data.values()]
                reason_counts = Counter(ban_reasons)
                top_reasons = reason_counts.most_common(5)

                # Count by severity
                severity_counts = Counter(str(ban_info.get("severity", "3")) for ban_info in banlist_data.values())
                severity_map = {"1": "High", "2": "Medium", "3": "Low"}

                embed = discord.Embed(
                    title="OpenBanlist stats",
                    description=f"There are **{total_banned}** active global bans",
                    color=0xfffffe
                )
                for reason, count in top_reasons:
                    embed.add_field(name=reason, value=f"**{count}** users", inline=False)
                for sev in ("1", "2", "3"):
                    embed.add_field(
                        name=f"Severity {sev} ({severity_map[sev]})",
                        value=f"**{severity_counts.get(sev, 0)}** bans",
                        inline=True
                    )
                await ctx.send(embed=embed)

    @commands.admin_or_permissions(manage_guild=True)
    @banlist.command(name="scan")
    async def scan(self, ctx):
        """
        Manually scan the server and take the configured action on any banned accounts found.
        """
        guild = ctx.guild
        enabled = await self.config.guild(guild).enabled()
        if not enabled:
            embed = discord.Embed(
                title="Banlist protection is disabled",
                description="Enable banlist protection with `banlist enable` before scanning.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        actions = await self.config.guild(guild).actions()
        if all(a == "none" for a in actions.values()):
            embed = discord.Embed(
                title="No action configured",
                description="Set actions for each severity (`banlist action set <severity> <action>`) before scanning.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        log_channel_id = await self.config.guild(guild).log_channel()
        log_channel = guild.get_channel(log_channel_id) if log_channel_id else None

        await ctx.send("🔍 Scanning server for users on the OpenBanlist...")

        async with self.session.get(self.banlist_url) as response:
            if response.status != 200:
                await ctx.send("Failed to fetch the banlist. Please try again later.")
                return
            banlist_data = await response.json()
            # Build a dict by reported_id for fast lookup
            ban_ids = {int(ban_info.get("reported_id", 0)): ban_info for ban_info in banlist_data.values()}

        found = []
        failed = []
        severity_map = {"1": "High", "2": "Medium", "3": "Low"}
        for member in guild.members:
            if member.bot:
                continue
            ban_info = ban_ids.get(member.id)
            if ban_info:
                # Skip if appeal_verdict is accepted
                appeal_info = ban_info.get("appeal_info", {})
                if appeal_info.get("appeal_verdict", "").lower() == "accepted":
                    continue
                severity = str(ban_info.get("severity", "3"))
                action = actions.get(severity, "none")
                try:
                    if action == "kick":
                        try:
                            embed_dm = discord.Embed(
                                title="You're unable to stay in this server",
                                description="You have been removed from the server due to an active ban on OpenBanlist.",
                                color=0xff4545
                            )
                            embed_dm.add_field(name="Appeal", value="To appeal, please visit [openbanlist.cc/appeal](https://openbanlist.cc/appeal).", inline=False)
                            await member.send(embed=embed_dm)
                        except discord.Forbidden:
                            pass
                        await member.kick(reason=f"Active ban detected on OpenBanlist (manual scan, severity {severity})")
                        action_taken = "kicked"
                    elif action == "ban":
                        try:
                            embed_dm = discord.Embed(
                                title="You're unable to stay in this server",
                                description="You have been banned from the server due to an active ban on OpenBanlist.",
                                color=0xff4545
                            )
                            embed_dm.add_field(name="Appeal", value="To appeal, please visit [openbanlist.cc/appeal](https://openbanlist.cc/appeal).", inline=False)
                            await member.send(embed=embed_dm)
                        except discord.Forbidden:
                            pass
                        await member.ban(reason=f"Active ban detected on OpenBanlist (manual scan, severity {severity})")
                        action_taken = "banned"
                    elif action == "timeout":
                        try:
                            embed_dm = discord.Embed(
                                title="You have been timed out in this server",
                                description="You have been timed out due to an active ban on OpenBanlist. You will not be able to interact in this server.",
                                color=0xffa500
                            )
                            embed_dm.add_field(name="Appeal", value="To appeal, please visit [openbanlist.cc/appeal](https://openbanlist.cc/appeal).", inline=False)
                            await member.send(embed=embed_dm)
                        except discord.Forbidden:
                            pass
                        try:
                            await member.timeout(until=discord.utils.utcnow() + timedelta(seconds=TIMEOUT_DURATION), reason=f"Active ban detected on OpenBanlist (manual scan, severity {severity})")
                            action_taken = "timed out"
                        except Exception:
                            action_taken = "failed to timeout"
                    else:
                        action_taken = "none"
                    found.append((member, ban_info, action_taken))
                except discord.Forbidden:
                    failed.append((member, ban_info))
                    continue

                # Log each action if log_channel is set
                if log_channel:
                    embed = discord.Embed(
                        title="Banlist match found (manual scan)",
                        description=f"{member.mention} ({member.id}) is actively listed on OpenBanlist.",
                        color=0xff4545
                    )
                    embed.add_field(name="Action taken", value=action_taken, inline=False)
                    embed.add_field(name="Ban reason", value=ban_info.get("ban_reason", "No reason provided"), inline=False)
                    embed.add_field(name="Context", value=ban_info.get("context", "No context provided"), inline=False)
                    embed.add_field(name="Severity", value=f"{severity} ({severity_map.get(severity, 'Unknown')})", inline=True)
                    # Process reporter name if available
                    reporter_id = ban_info.get("reporter_id", "Unknown")
                    reporter_name = ban_info.get("reporter_name", None)
                    if reporter_name:
                        reporter_display = f"{reporter_name} (<@{reporter_id}>)"
                    else:
                        reporter_display = f"<@{reporter_id}>"
                    embed.add_field(name="Reporter", value=reporter_display, inline=False)
                    approver_id = ban_info.get("approver_id", "Unknown")
                    approver_name = ban_info.get("approver_name", None)
                    if approver_name:
                        approver_display = f"{approver_name} (<@{approver_id}>)"
                    else:
                        approver_display = f"<@{approver_id}>"
                    embed.add_field(name="Approver", value=approver_display, inline=False)
                    embed.add_field(name="Appealable", value=str(ban_info.get("appealable", False)), inline=False)
                    if ban_info.get("appealed", False):
                        appeal_info = ban_info.get("appeal_info", {})
                        appeal_verdict = appeal_info.get("appeal_verdict", "")
                        if not appeal_verdict:
                            appeal_status = "Pending"
                        elif appeal_verdict == "accepted":
                            appeal_status = "Accepted"
                        elif appeal_verdict == "denied":
                            appeal_status = "Denied"
                        else:
                            appeal_status = "Unknown"
                        embed.add_field(name="Appeal status", value=appeal_status, inline=True)
                        embed.add_field(name="Appeal verdict", value=appeal_verdict or "No verdict provided", inline=False)
                        appeal_reason = appeal_info.get("appeal_reason", "")
                        if appeal_reason:
                            embed.add_field(name="Appeal reason", value=appeal_reason, inline=False)
                    evidence = ban_info.get("evidence", "")
                    if evidence:
                        embed.set_image(url=evidence)
                    report_date = ban_info.get("report_date", "Unknown")
                    ban_date = ban_info.get("ban_date", "Unknown")
                    if report_date != "Unknown":
                        embed.add_field(name="Report date", value=f"<t:{report_date}:F>", inline=False)
                    else:
                        embed.add_field(name="Report date", value="Unknown", inline=False)
                    if ban_date != "Unknown":
                        embed.add_field(name="Ban date", value=f"<t:{ban_date}:F>", inline=False)
                    else:
                        embed.add_field(name="Ban date", value="Unknown", inline=False)
                    await log_channel.send(embed=embed)

        summary_embed = discord.Embed(
            title="OpenBanlist scan complete",
            color=0x2bbd8e if found or failed else 0xfffffe
        )
        summary_embed.add_field(name="Total scanned", value=str(len(guild.members)), inline=True)
        summary_embed.add_field(name="Matches found", value=str(len(found)), inline=True)
        summary_embed.add_field(name="Failed actions", value=str(len(failed)), inline=True)
        if found:
            summary_embed.add_field(
                name="Users affected",
                value="\n".join(f"{m.mention} ({m.id}) - {a}" for m, _, a in found)[:1024],
                inline=False
            )
        if failed:
            summary_embed.add_field(
                name="Failed to act on",
                value="\n".join(f"{m.mention} ({m.id})" for m, _ in failed)[:1024],
                inline=False
            )
        await ctx.send(embed=summary_embed)

    async def update_banlist_periodically(self):
        while True:
            await self.update_banlist()
            await asyncio.sleep(86400)  # 24 hours

    async def update_banlist(self):
        async with self.session.get(self.banlist_url) as response:
            if response.status == 200:
                banlist_data = await response.json()
                for guild in self.bot.guilds:
                    if await self.config.guild(guild).enabled():
                        await self.enforce_banlist(guild, banlist_data)

    async def enforce_banlist(self, guild, banlist_data):
        actions = await self.config.guild(guild).actions()
        if all(a == "none" for a in actions.values()):
            return

        # Build a dict by reported_id for fast lookup
        ban_ids = {int(ban_info.get("reported_id", 0)): ban_info for ban_info in banlist_data.values()}
        severity_map = {"1": "High", "2": "Medium", "3": "Low"}

        for member in guild.members:
            ban_info = ban_ids.get(member.id)
            if ban_info:
                appeal_info = ban_info.get("appeal_info", {})
                if appeal_info.get("appeal_verdict", "").lower() == "accepted":
                    continue
                severity = str(ban_info.get("severity", "3"))
                action = actions.get(severity, "none")
                try:
                    if action == "kick":
                        await member.kick(reason=f"Active ban detected on OpenBanlist (severity {severity})")
                    elif action == "ban":
                        await member.ban(reason=f"Active ban detected on OpenBanlist (severity {severity})")
                    elif action == "timeout":
                        try:
                            await member.timeout(until=discord.utils.utcnow() + timedelta(seconds=TIMEOUT_DURATION), reason=f"Active ban detected on OpenBanlist (severity {severity})")
                        except Exception:
                            pass
                except discord.Forbidden:
                    pass

    async def timeout_enforcer(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    enabled = await self.config.guild(guild).enabled()
                    if not enabled:
                        continue
                    actions = await self.config.guild(guild).actions()
                    if all(a == "none" for a in actions.values()):
                        continue
                    log_channel_id = await self.config.guild(guild).log_channel()
                    log_channel = guild.get_channel(log_channel_id) if log_channel_id else None

                    async with self.session.get(self.banlist_url) as response:
                        if response.status != 200:
                            continue
                        banlist_data = await response.json()
                        ban_ids = {int(ban_info.get("reported_id", 0)): ban_info for ban_info in banlist_data.values()}
                        severity_map = {"1": "High", "2": "Medium", "3": "Low"}
                        for member in guild.members:
                            if member.bot:
                                continue
                            ban_info = ban_ids.get(member.id)
                            if not ban_info:
                                continue
                            appeal_info = ban_info.get("appeal_info", {})
                            if appeal_info.get("appeal_verdict", "").lower() == "accepted":
                                continue
                            severity = str(ban_info.get("severity", "3"))
                            action = actions.get(severity, "none")
                            if action == "timeout":
                                # Only re-timeout if not already timed out for the max duration
                                try:
                                    if hasattr(member, "timed_out_until") and member.timed_out_until:
                                        # If timeout is expiring in less than 1 day, re-apply
                                        if (member.timed_out_until - discord.utils.utcnow()).total_seconds() < 24 * 60 * 60:
                                            await member.timeout(until=discord.utils.utcnow() + timedelta(seconds=TIMEOUT_DURATION), reason="OpenBanlist timeout enforcement")
                                    else:
                                        await member.timeout(until=discord.utils.utcnow() + timedelta(seconds=TIMEOUT_DURATION), reason="OpenBanlist timeout enforcement")
                                except Exception:
                                    pass
            except Exception:
                pass
            await asyncio.sleep(60 * 60)  # Run every hour

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        if not await self.config.guild(guild).enabled():
            return

        async with self.session.get(self.banlist_url) as response:
            if response.status == 200:
                banlist_data = await response.json()
                log_channel_id = await self.config.guild(guild).log_channel()
                log_channel = guild.get_channel(log_channel_id)

                # Find all bans for this member, if any, by reported_id
                user_bans = []
                banlist_items = list(banlist_data.items())
                for idx, (ban_key, ban_info) in enumerate(banlist_items, 1):
                    if int(ban_info.get("reported_id", 0)) == member.id:
                        user_bans.append((idx, ban_info))
                # Only consider bans that are still active (appeal_verdict is not "accepted")
                active_bans = [ban_info for idx, ban_info in user_bans if ban_info.get("appeal_info", {}).get("appeal_verdict", "").lower() != "accepted"]

                severity_map = {"1": "High", "2": "Medium", "3": "Low"}
                actions = await self.config.guild(guild).actions()

                # If there are active bans, process as before
                if user_bans:
                    if active_bans:
                        # There is at least one active ban
                        active_ban = active_bans[0]
                        severity = str(active_ban.get("severity", "3"))
                        action = actions.get(severity, "none")
                        try:
                            if action == "kick":
                                try:
                                    embed = discord.Embed(
                                        title="You're unable to join this server",
                                        description="You have been removed from the server due to an active ban on OpenBanlist.",
                                        color=0xff4545
                                    )
                                    embed.add_field(name="Severity", value=f"{severity} ({severity_map.get(severity, 'Unknown')})", inline=True)
                                    embed.add_field(name="Appeal", value="To appeal, please visit [openbanlist.cc/appeal](https://openbanlist.cc/appeal).", inline=False)
                                    await member.send(embed=embed)
                                except discord.Forbidden:
                                    pass
                                await member.kick(reason=f"Active ban detected on OpenBanlist (severity {severity})")
                                action_taken = "kicked"
                            elif action == "ban":
                                try:
                                    embed = discord.Embed(
                                        title="You're unable to join this server",
                                        description="You have been banned from the server due to an active ban on OpenBanlist.",
                                        color=0xff4545
                                    )
                                    embed.add_field(name="Severity", value=f"{severity} ({severity_map.get(severity, 'Unknown')})", inline=True)
                                    embed.add_field(name="Appeal", value="To appeal, please visit [openbanlist.cc/appeal](https://openbanlist.cc/appeal).", inline=False)
                                    await member.send(embed=embed)
                                except discord.Forbidden:
                                    pass
                                await member.ban(reason=f"Active ban detected on OpenBanlist (severity {severity})")
                                action_taken = "banned"
                            elif action == "timeout":
                                try:
                                    embed = discord.Embed(
                                        title="You have been timed out in this server",
                                        description="You have been timed out due to an active ban on OpenBanlist. You will not be able to interact in this server.",
                                        color=0xffa500
                                    )
                                    embed.add_field(name="Severity", value=f"{severity} ({severity_map.get(severity, 'Unknown')})", inline=True)
                                    embed.add_field(name="Appeal", value="To appeal, please visit [openbanlist.cc/appeal](https://openbanlist.cc/appeal).", inline=False)
                                    await member.send(embed=embed)
                                except discord.Forbidden:
                                    pass
                                try:
                                    await member.timeout(until=discord.utils.utcnow() + timedelta(seconds=TIMEOUT_DURATION), reason=f"Active ban detected on OpenBanlist (severity {severity})")
                                    action_taken = "timed out"
                                except Exception:
                                    action_taken = "failed to timeout"
                            else:
                                action_taken = "none"
                        except discord.Forbidden:
                            action_taken = "failed due to permissions"

                        if log_channel:
                            embed = discord.Embed(
                                title="Banlist match found",
                                description=f"{member.mention} ({member.id}) joined and is actively listed on OpenBanlist.",
                                color=0xff4545
                            )
                            embed.add_field(name="Action taken", value=action_taken, inline=False)
                            embed.add_field(name="Ban reason", value=active_ban.get("ban_reason", "No reason provided"), inline=False)
                            embed.add_field(name="Context", value=active_ban.get("context", "No context provided"), inline=False)
                            embed.add_field(name="Severity", value=f"{severity} ({severity_map.get(severity, 'Unknown')})", inline=True)
                            # Process reporter name if available
                            reporter_id = active_ban.get("reporter_id", "Unknown")
                            reporter_name = active_ban.get("reporter_name", None)
                            if reporter_name:
                                reporter_display = f"{reporter_name} (<@{reporter_id}>)"
                            else:
                                reporter_display = f"<@{reporter_id}>"
                            embed.add_field(name="Reporter", value=reporter_display, inline=False)
                            approver_id = active_ban.get("approver_id", "Unknown")
                            approver_name = active_ban.get("approver_name", None)
                            if approver_name:
                                approver_display = f"{approver_name} (<@{approver_id}>)"
                            else:
                                approver_display = f"<@{approver_id}>"
                            embed.add_field(name="Approver", value=approver_display, inline=False)
                            embed.add_field(name="Appealable", value=str(active_ban.get("appealable", False)), inline=False)
                            if active_ban.get("appealed", False):
                                appeal_info = active_ban.get("appeal_info", {})
                                appeal_verdict = appeal_info.get("appeal_verdict", "")
                                if not appeal_verdict:
                                    appeal_status = "Pending"
                                elif appeal_verdict == "accepted":
                                    # If the appeal is accepted, this ban should not be considered active, so skip showing as active
                                    # Instead, fall through to the else block below
                                    active_bans = []
                                elif appeal_verdict == "denied":
                                    appeal_status = "Denied"
                                else:
                                    appeal_status = "Unknown"
                                if active_bans:
                                    embed.add_field(name="Appeal status", value=appeal_status, inline=True)
                                    embed.add_field(name="Appeal verdict", value=appeal_verdict or "No verdict provided", inline=False)
                                    appeal_reason = appeal_info.get("appeal_reason", "")
                                    if appeal_reason:
                                        embed.add_field(name="Appeal reason", value=appeal_reason, inline=False)
                            if active_bans:
                                evidence = active_ban.get("evidence", "")
                                if evidence:
                                    embed.set_image(url=evidence)
                                report_date = active_ban.get("report_date", "Unknown")
                                ban_date = active_ban.get("ban_date", "Unknown")
                                if report_date != "Unknown":
                                    embed.add_field(name="Report date", value=f"<t:{report_date}:F>", inline=False)
                                else:
                                    embed.add_field(name="Report date", value="Unknown", inline=False)
                                if ban_date != "Unknown":
                                    embed.add_field(name="Ban date", value=f"<t:{ban_date}:F>", inline=False)
                                else:
                                    embed.add_field(name="Ban date", value="Unknown", inline=False)
                                await log_channel.send(embed=embed)
                                return  # Only send the active ban embed if still valid
                    # If we get here, either there are no active bans, or the only ban(s) have an accepted appeal
                    if log_channel:
                        embed = discord.Embed(
                            title="User join screened",
                            description=f"**{member.mention}** ({member.id}) joined the server and has a punishment history on OpenBanlist",
                            color=discord.Color.orange()
                        )
                        # Add a single field for prior bans as per instructions
                        prior_bans_lines = []
                        for idx, ban_info in user_bans:
                            reason = ban_info.get("ban_reason", "No reason provided")
                            ban_date = ban_info.get("ban_date", None)
                            severity = str(ban_info.get("severity", "3"))
                            if ban_date and ban_date != "Unknown":
                                try:
                                    # ban_date is a unix timestamp, so use Discord dynamic timestamp
                                    date_str = f"<t:{int(ban_date)}:F>"
                                except Exception:
                                    date_str = str(ban_date)
                            else:
                                date_str = "Unknown"
                            prior_bans_lines.append(f"`#{idx}` for **{reason}** (Severity {severity_map.get(severity, 'Unknown')}) on **{date_str}**")
                        if prior_bans_lines:
                            embed.add_field(
                                name="Prior bans",
                                value="\n".join(prior_bans_lines),
                                inline=False
                            )
                        embed.set_footer(text="Powered by OpenBanlist, a BeeHive service | openbanlist.cc")
                        await log_channel.send(embed=embed)
                else:
                    if log_channel:
                        embed = discord.Embed(
                            title="User join screened",
                            description=f"**{member.mention}** ({member.id}) joined the server and passed all banlist checks",
                            color=0x2bbd8e
                        )
                        embed.set_footer(text="Powered by OpenBanlist, a BeeHive service | openbanlist.cc")
                        await log_channel.send(embed=embed)
