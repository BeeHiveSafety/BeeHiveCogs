from redbot.core import commands, Config # type: ignore
import discord
import aiohttp
import asyncio
from collections import Counter

class OpenBanList(commands.Cog):
    """
    OpenBanlist is a project aimed at cataloging malicious Discord users and working to keep them out of servers in a united fashion.
    
    For more information or to report a user, please visit [openbanlist.cc](<https://openbanlist.cc>)
    """

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "enabled": False,
            "action": "none",  # Default action is none
            "log_channel": None  # Default log channel is None
        }
        self.config.register_guild(**default_guild)
        self.banlist_url = "https://openbanlist.cc/data/banlist.json"
        self.session = aiohttp.ClientSession()
        self.bot.loop.create_task(self.update_banlist_periodically())

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

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
    @banlist.command()
    async def action(self, ctx, action: str):
        """Set the action to take against users on the banlist."""
        valid_actions = ["kick", "ban", "none"]
        if action not in valid_actions:
            embed = discord.Embed(
                title="Invalid action",
                description=f"Invalid action. Choose from: {', '.join(valid_actions)}",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return
        await self.config.guild(ctx.guild).action.set(action)
        embed = discord.Embed(
            title="OpenBanlist action set",
            description=f"Action for users on the banlist set to: {action}",
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
                ban_info = next((ban_info for ban_info in banlist_data.values() if int(ban_info["reported_id"]) == user_id), None)
                
                if ban_info:
                    embed = discord.Embed(
                        title="OpenBanlist check",
                        description=f"> Uh oh! <@{user_id}> is listed in the **[OpenBanlist](https://openbanlist.cc)**",
                        color=0xff4545
                    )
                    embed.add_field(name="Banned for", value=ban_info.get("ban_reason", "No reason provided yet, check back soon"), inline=True)
                    embed.add_field(name="Context", value=ban_info.get("context", "No context provided"), inline=False)
                    embed.add_field(name="Reported by", value=f"<@{ban_info.get('reporter_id', 'Unknown')}>\n`{ban_info.get('reporter_id', 'Unknown')}`", inline=True)
                    embed.add_field(name="Approved by", value=f"<@{ban_info.get('approver_id', 'Unknown')}>\n`{ban_info.get('approver_id', 'Unknown')}`", inline=True)
                    appealable_status = ":white_check_mark: **Yes**" if ban_info.get("appealable", False) else ":x: **Not eligible**"
                    embed.add_field(name="Can be appealed?", value=appealable_status, inline=True)
                    if ban_info.get("appealed", False):
                        appeal_verdict = ban_info.get("appeal_verdict", "")
                        if not appeal_verdict:
                            appeal_status = "Pending"
                        elif appeal_verdict == "accepted":
                            appeal_status = "Accepted"
                        elif appeal_verdict == "denied":
                            appeal_status = "Denied"
                        else:
                            appeal_status = "Unknown"
                        embed.add_field(name="Appeal status", value=appeal_status, inline=True)
                        embed.add_field(name="Appeal verdict", value=ban_info.get("appeal_verdict", "No verdict provided"), inline=False)
                        appeal_reason = ban_info.get("appeal_reason", "")
                        if appeal_reason:
                            embed.add_field(name="Appeal reason", value=appeal_reason, inline=False)
                    evidence = ban_info.get("evidence", "")
                    if evidence:
                        embed.set_image(url=evidence)
                    report_date = ban_info.get("report_date", "Unknown")
                    ban_date = ban_info.get("ban_date", "Unknown")
                    if report_date != "Unknown":
                        embed.add_field(name="Reported on", value=f"<t:{report_date}:f>", inline=True)
                    else:
                        embed.add_field(name="Report date", value="Unknown", inline=True)
                    if ban_date != "Unknown":
                        embed.add_field(name="Added to database", value=f"<t:{ban_date}:f>", inline=True)
                    else:
                        embed.add_field(name="Ban date", value="Unknown", inline=True)
                else:
                    embed = discord.Embed(
                        title="OpenBanlist check",
                        description=f"User ID {user_id} is not on the banlist.",
                        color=0x2bbd8e
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

                embed = discord.Embed(
                    title="OpenBanlist stats",
                    description=f"There are **{total_banned}** active global bans",
                    color=0xfffffe
                )
                for reason, count in top_reasons:
                    embed.add_field(name=reason, value=f"**{count}** users", inline=False)
                await ctx.send(embed=embed)

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
        action = await self.config.guild(guild).action()
        if action == "none":
            return

        for member in guild.members:
            if any(member.id == int(ban_info["reported_id"]) for ban_info in banlist_data.values()):
                try:
                    if action == "kick":
                        await member.kick(reason="Active ban detected on OpenBanlist")
                    elif action == "ban":
                        await member.ban(reason="Active ban detected on OpenBanlist")
                except discord.Forbidden:
                    pass

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

                if any(member.id == int(ban_info["reported_id"]) for ban_info in banlist_data.values()):
                    action = await self.config.guild(guild).action()
                    ban_info = next(ban_info for ban_info in banlist_data.values() if member.id == int(ban_info["reported_id"]))
                    try:
                        if action == "kick":
                            try:
                                embed = discord.Embed(
                                    title="You're unable to join this server",
                                    description="You have been removed from the server due to an active ban on OpenBanlist.",
                                    color=0xff4545
                                )
                                embed.add_field(name="Appeal", value="To appeal, please visit [openbanlist.cc/appeal](https://openbanlist.cc/appeal).", inline=False)
                                await member.send(embed=embed)
                            except discord.Forbidden:
                                pass
                            await member.kick(reason="Active ban detected on OpenBanlist")
                            action_taken = "kicked"
                        elif action == "ban":
                            try:
                                embed = discord.Embed(
                                    title="You're unable to join this server",
                                    description="You have been banned from the server due to an active ban on OpenBanlist.",
                                    color=0xff4545
                                )
                                embed.add_field(name="Appeal", value="To appeal, please visit [openbanlist.cc/appeal](https://openbanlist.cc/appeal).", inline=False)
                                await member.send(embed=embed)
                            except discord.Forbidden:
                                pass
                            await member.ban(reason="Active ban detected on OpenBanlist")
                            action_taken = "banned"
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
                        embed.add_field(name="Ban reason", value=ban_info.get("ban_reason", "No reason provided"), inline=False)
                        embed.add_field(name="Context", value=ban_info.get("context", "No context provided"), inline=False)
                        embed.add_field(name="Reporter ID", value=ban_info.get("reporter_id", "Unknown"), inline=False)
                        embed.add_field(name="Approver ID", value=ban_info.get("approver_id", "Unknown"), inline=False)
                        embed.add_field(name="Appealable", value=str(ban_info.get("appealable", False)), inline=False)
                        if ban_info.get("appealed", False):
                            appeal_verdict = ban_info.get("appeal_verdict", "")
                            if not appeal_verdict:
                                appeal_status = "Pending"
                            elif appeal_verdict == "accepted":
                                appeal_status = "Accepted"
                            elif appeal_verdict == "denied":
                                appeal_status = "Denied"
                            else:
                                appeal_status = "Unknown"
                            embed.add_field(name="Appeal status", value=appeal_status, inline=True)
                            embed.add_field(name="Appeal verdict", value=ban_info.get("appeal_verdict", "No verdict provided"), inline=False)
                            appeal_reason = ban_info.get("appeal_reason", "")
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
                else:
                    if log_channel:
                        embed = discord.Embed(
                            title="User join screened",
                            description=f"**{member.mention}** ({member.id}) joined the server, and no active ban was found on the OpenBanlist.",
                            color=0x2bbd8e
                        )
                        embed.set_footer(text="Powered by OpenBanlist, a BeeHive service | openbanlist.cc")
                        await log_channel.send(embed=embed)
