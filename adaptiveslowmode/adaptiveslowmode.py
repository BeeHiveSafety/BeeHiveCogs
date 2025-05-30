import discord # type: ignore
from redbot.core import commands, Config, checks # type: ignore
from datetime import datetime, timezone, timedelta
import asyncio
from collections import deque, defaultdict

def loop(*, seconds=0, minutes=0, hours=0):
    """A simple replacement for tasks.loop for Red 3.5+ compatibility."""
    def decorator(func):
        async def loop_runner(self, *args, **kwargs):
            await self.bot.wait_until_ready()
            while True:
                await func(self, *args, **kwargs)
                await asyncio.sleep(seconds + minutes * 60 + hours * 3600)
        func._loop_runner = loop_runner
        return func
    return decorator

def plural(n, singular, plural=None):
    """Return singular/plural form based on n."""
    if n == 1:
        return singular
    return plural if plural is not None else singular + "s"

class AdaptiveSlowmode(commands.Cog):
    """
    Dynamically adjust channel slowmode in 1-second increments based on activity to keep chat readable and moderatable.
    """

    DEFAULTS = {
        "enabled": False,
        "min_slowmode": 0,
        "max_slowmode": 120,
        "target_msgs_per_min": 20,
        "channels": [],
        "log_channel": None,
    }

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xBEEBEE01, force_registration=True)
        self.config.register_guild(**self.DEFAULTS)
        self._message_cache = defaultdict(lambda: deque(maxlen=500))
        self._lock = asyncio.Lock()
        self._slowmode_task = self.bot.loop.create_task(self._run_slowmode_task())
        self._minute_stats = defaultdict(lambda: deque(maxlen=5))  # channel_id: deque of last 5 minute counts
        self._minute_tick = 0  # Used to track when to send the 5-min report
        self._last_log_message = {}  # channel_id: discord.Message

    def cog_unload(self):
        if hasattr(self, "_slowmode_task"):
            self._slowmode_task.cancel()

    @commands.group()
    @commands.guild_only()
    @checks.admin_or_permissions(manage_guild=True)
    async def adaptiveslowmode(self, ctx):
        """Adaptive slowmode configuration."""
        pass

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def enable(self, ctx):
        """Enable adaptive slowmode for this server."""
        await self.config.guild(ctx.guild).enabled.set(True)
        embed = discord.Embed(
            title="Adaptive slowmode",
            description="Adaptive slowmode enabled.",
            color=0x2bbd8e
        )
        await ctx.send(embed=embed)

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def disable(self, ctx):
        """Disable adaptive slowmode for this server."""
        await self.config.guild(ctx.guild).enabled.set(False)
        embed = discord.Embed(
            title="Adaptive slowmode",
            description="Adaptive slowmode disabled.",
            color=0xff4545
        )
        await ctx.send(embed=embed)

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def min(self, ctx, seconds: int):
        """Set minimum slowmode (in seconds)."""
        await self.config.guild(ctx.guild).min_slowmode.set(seconds)
        embed = discord.Embed(
            title="Adaptive slowmode",
            description=f"Minimum slowmode set to {seconds} {plural(seconds, 'second')}.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def max(self, ctx, seconds: int):
        """Set maximum slowmode (in seconds)."""
        await self.config.guild(ctx.guild).max_slowmode.set(seconds)
        embed = discord.Embed(
            title="Adaptive slowmode",
            description=f"Maximum slowmode set to {seconds} {plural(seconds, 'second')}.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def target(self, ctx, msgs_per_min: int):
        """Set target messages per minute for a channel."""
        await self.config.guild(ctx.guild).target_msgs_per_min.set(msgs_per_min)
        embed = discord.Embed(
            title="Adaptive slowmode",
            description=f"Target {plural(msgs_per_min, 'message')} per minute set to {msgs_per_min}.",
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def add(self, ctx, channel: discord.TextChannel):
        """Add a channel to adaptive slowmode."""
        async with self.config.guild(ctx.guild).channels() as chans:
            if channel.id not in chans:
                chans.append(channel.id)
        embed = discord.Embed(
            title="Adaptive slowmode",
            description=f"{channel.mention} added to dynamic slowmode.",
            color=0x2bbd8e
        )
        await ctx.send(embed=embed)

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def remove(self, ctx, channel: discord.TextChannel):
        """Remove a channel from adaptive slowmode."""
        async with self.config.guild(ctx.guild).channels() as chans:
            if channel.id in chans:
                chans.remove(channel.id)
        embed = discord.Embed(
            title="Adaptive slowmode",
            description=f"{channel.mention} removed from dynamic slowmode.",
            color=0xff4545
        )
        await ctx.send(embed=embed)

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command(name="settings")
    async def _settings(self, ctx):
        """Show current adaptive slowmode settings and status."""
        conf = await self.config.guild(ctx.guild).all()
        enabled = conf["enabled"]
        min_slowmode = conf["min_slowmode"]
        max_slowmode = conf["max_slowmode"]
        target_mpm = conf["target_msgs_per_min"]
        log_channel_id = conf["log_channel"]
        log_channel = ctx.guild.get_channel(log_channel_id) if log_channel_id else None
        chans = conf["channels"]
        channels = [ctx.guild.get_channel(cid) for cid in chans]
        channels = [c.mention for c in channels if c]

        embed = discord.Embed(
            title="Adaptive slowmode settings",
            color=0xfffffe
        )
        embed.add_field(name="Enabled", value=str(enabled), inline=False)
        embed.add_field(name="Min slowmode", value=f"{min_slowmode} {plural(min_slowmode, 'second')}", inline=True)
        embed.add_field(name="Max slowmode", value=f"{max_slowmode} {plural(max_slowmode, 'second')}", inline=True)
        embed.add_field(name="Target Messages/Minute", value=str(target_mpm), inline=True)
        embed.add_field(name="Log channel", value=log_channel.mention if log_channel else "None", inline=False)
        embed.add_field(name="Channels", value="\n".join(channels) if channels else "No channels set", inline=False)

        await ctx.send(embed=embed)

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def logs(self, ctx, channel: discord.TextChannel = None):
        """
        Set the logging channel for adaptive slowmode events.
        Use without a channel to clear the log channel.
        """
        if channel is None:
            await self.config.guild(ctx.guild).log_channel.set(None)
            embed = discord.Embed(
                title="Adaptive slowmode",
                description="Adaptive slowmode log channel cleared.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
        else:
            await self.config.guild(ctx.guild).log_channel.set(channel.id)
            embed = discord.Embed(
                title="Adaptive slowmode",
                description=f"Adaptive slowmode log channel set to {channel.mention}.",
                color=0x2bbd8e
            )
            await ctx.send(embed=embed)

    async def _send_log(self, guild: discord.Guild, embed: discord.Embed, view: discord.ui.View = None):
        log_channel_id = await self.config.guild(guild).log_channel()
        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel and log_channel.permissions_for(guild.me).send_messages:
                try:
                    # If this is a 5-min log (view is SlowmodeLogView), disable the previous one for this channel
                    channel_id = None
                    if view and hasattr(view, "channel"):
                        channel_id = getattr(view, "channel", None)
                        if channel_id is not None:
                            channel_id = view.channel.id
                    if channel_id is not None and hasattr(self, "_last_log_message"):
                        last_msg = self._last_log_message.get(channel_id)
                        if last_msg:
                            try:
                                # Disable all buttons in the previous view
                                if last_msg.components:
                                    # Discord.py 2.x: edit with disabled view
                                    # Rebuild the view with all items disabled
                                    old_view = None
                                    try:
                                        # Try to reconstruct the view from the message
                                        # This is a best effort, as discord.py does not provide a direct way
                                        # We'll just disable all items in the old view if possible
                                        # But since we have the view object, we can just disable it
                                        # (if we kept the view object, but we don't, so we reconstruct)
                                        pass
                                    except Exception:
                                        pass
                                    # Instead, just try to edit with a disabled view
                                    # We'll create a new view with all items disabled
                                    if isinstance(view, discord.ui.View):
                                        disabled_view = type(view)(
                                            view.cog, view.channel, view.current, view.min_slow, view.max_slow
                                        )
                                        for item in disabled_view.children:
                                            item.disabled = True
                                        await last_msg.edit(view=disabled_view)
                                    else:
                                        # fallback: try to remove the view
                                        await last_msg.edit(view=None)
                                else:
                                    await last_msg.edit(view=None)
                            except Exception:
                                pass
                    # Send the new log message and store it if it's a 5-min log
                    sent_msg = await log_channel.send(embed=embed, view=view)
                    if channel_id is not None:
                        self._last_log_message[channel_id] = sent_msg
                except discord.Forbidden:
                    print(f"Permission error: Cannot send log message to {log_channel.mention}.")
                except discord.HTTPException as e:
                    print(f"HTTP error: Failed to send log message to {log_channel.mention}: {e}")
                except Exception as e:
                    print(f"Unexpected error: Failed to send log message to {log_channel.mention}: {e}")

    @checks.admin_or_permissions(manage_guild=True)
    @adaptiveslowmode.command()
    async def survey(self, ctx, channel: discord.TextChannel = None):
        """
        Calibrate adaptive slowmode for a channel by measuring 5 minutes of activity.
        Sets the target messages per minute and suggests min/max slowmode.
        """
        channel = channel or ctx.channel
        embed = discord.Embed(
            title="Engagement survey ongoing",
            description=f"Survey started for {channel.mention}. I'll be back soon with results...",
            color=0x2bbd8e
        )
        await ctx.send(embed=embed)

        # Record the start time and count messages after
        start_time = datetime.now(timezone.utc)
        msg_count_5min = 0

        def check(m):
            return m.channel == channel and m.created_at >= start_time

        try:
            while (datetime.now(timezone.utc) - start_time).total_seconds() < 300:
                msg = await self.bot.wait_for('message', timeout=300, check=check)
                if msg:
                    msg_count_5min += 1
        except asyncio.TimeoutError:
            pass

        # Calculate messages per minute
        msgs_per_min = msg_count_5min / 5

        # Suggest min/max slowmode based on activity
        if msgs_per_min > 60:
            min_slow = 2
            max_slow = 10
        elif msgs_per_min > 20:
            min_slow = 0
            max_slow = 10
        else:
            min_slow = 0
            max_slow = 5

        # Save these as the new config for the guild
        await self.config.guild(ctx.guild).target_msgs_per_min.set(int(msgs_per_min))
        await self.config.guild(ctx.guild).min_slowmode.set(min_slow)
        await self.config.guild(ctx.guild).max_slowmode.set(max_slow)
        async with self.config.guild(ctx.guild).channels() as chans:
            if channel.id not in chans:
                chans.append(channel.id)

        survey_result = (
            f"Survey complete for {channel.mention}!\n"
            f"{plural(msg_count_5min, 'Message')} in last 5 minutes: **{msg_count_5min}**\n"
            f"Average {plural(msgs_per_min, 'message')}/minute: **{msgs_per_min:.2f}**\n"
            f"Set target {plural(int(msgs_per_min), 'message')}/minute to **{int(msgs_per_min)}**\n"
            f"Set min slowmode to **{min_slow}**{plural(min_slow, 's', 's')},"  # always plural 's' for seconds
            f" max slowmode to **{max_slow}**{plural(max_slow, 's', 's')}.\n"
            f"{channel.mention} is now enabled for dynamic slowmode."
        )

        embed = discord.Embed(
            title="Engagement survey results",
            description=survey_result,
            color=0x2bbd8e
        )
        await ctx.send(embed=embed)
        await self._send_log(ctx.guild, embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        guild = message.guild
        conf = await self.config.guild(guild).all()
        if not conf["enabled"]:
            return
        if message.channel.id not in conf["channels"]:
            return
        now = datetime.now(timezone.utc)
        async with self._lock:
            # Store (timestamp, author_id) for user tracking
            self._message_cache[message.channel.id].append((now, message.author.id))

    async def _run_slowmode_task(self):
        await self.bot.wait_until_ready()
        while True:
            await self.slowmode_task()
            await asyncio.sleep(60)  # Run every minute

    class SlowmodeLogView(discord.ui.View):
        def __init__(self, cog, channel: discord.TextChannel, current: int, min_slow: int, max_slow: int):
            super().__init__(timeout=300)
            self.cog = cog
            self.channel = channel
            self.current = current
            self.min_slow = min_slow
            self.max_slow = max_slow

            # Add buttons
            self.add_item(AdaptiveSlowmode.IncreaseSlowmodeButton(cog, channel, current, max_slow))
            self.add_item(AdaptiveSlowmode.DecreaseSlowmodeButton(cog, channel, current, min_slow))

    class IncreaseSlowmodeButton(discord.ui.Button):
        def __init__(self, cog, channel: discord.TextChannel, current: int, max_slow: int):
            super().__init__(
                label="Increase slowmode",
                style=discord.ButtonStyle.grey,
                emoji="⏫",
                custom_id=f"increase_slowmode_{channel.id}",
                row=0,
                disabled=current >= max_slow
            )
            self.cog = cog
            self.channel = channel
            self.current = current
            self.max_slow = max_slow

        async def callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.manage_channels:
                await interaction.response.send_message("You don't have permission to adjust slowmode.", ephemeral=True)
                return
            new_slowmode = min(self.current + 1, self.max_slow)
            try:
                await self.channel.edit(slowmode_delay=new_slowmode, reason="Manual increase via log button")
                await interaction.response.send_message(
                    f"Slowmode for {self.channel.mention} increased to {new_slowmode} {plural(new_slowmode, 'second')}.", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to edit this channel.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Failed to increase slowmode: {e}", ephemeral=True)

    class DecreaseSlowmodeButton(discord.ui.Button):
        def __init__(self, cog, channel: discord.TextChannel, current: int, min_slow: int):
            super().__init__(
                label="Decrease slowmode",
                style=discord.ButtonStyle.grey,
                emoji="⏬",
                custom_id=f"decrease_slowmode_{channel.id}",
                row=0,
                disabled=current <= min_slow
            )
            self.cog = cog
            self.channel = channel
            self.current = current
            self.min_slow = min_slow

        async def callback(self, interaction: discord.Interaction):
            if not interaction.user.guild_permissions.manage_channels:
                await interaction.response.send_message("You don't have permission to adjust slowmode.", ephemeral=True)
                return
            new_slowmode = max(self.current - 1, self.min_slow)
            try:
                await self.channel.edit(slowmode_delay=new_slowmode, reason="Manual decrease via log button")
                await interaction.response.send_message(
                    f"Slowmode for {self.channel.mention} decreased to {new_slowmode} {plural(new_slowmode, 'second')}.", ephemeral=True
                )
            except discord.Forbidden:
                await interaction.response.send_message("I don't have permission to edit this channel.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"Failed to decrease slowmode: {e}", ephemeral=True)

    async def slowmode_task(self):
        # This runs every minute
        now = datetime.now(timezone.utc)
        window_seconds = 60
        report_every = 5  # minutes

        for guild in self.bot.guilds:
            conf = await self.config.guild(guild).all()
            if not conf["enabled"]:
                continue
            min_slow = conf["min_slowmode"]
            max_slow = conf["max_slowmode"]
            target_mpm = conf["target_msgs_per_min"]
            for cid in conf["channels"]:
                channel = guild.get_channel(cid)
                if not channel or not isinstance(channel, discord.TextChannel):
                    continue
                async with self._lock:
                    # Remove messages older than 5 minutes for stats, but only count last minute for slowmode
                    cache = self._message_cache[cid]
                    while cache and (now - cache[0][0]).total_seconds() > 300:
                        cache.popleft()
                    # Count messages in the last minute
                    minute_ago = now - timedelta(seconds=window_seconds)
                    msg_count_minute = sum(1 for t, _ in cache if t > minute_ago)
                    # Track per-minute stats for reporting
                    self._minute_stats[cid].append(msg_count_minute)
                # Calculate new slowmode in 1-second increments
                current = channel.slowmode_delay
                if msg_count_minute > target_mpm:
                    # Too fast, increase slowmode by 1 second
                    new_slowmode = min(current + 1, max_slow)
                elif msg_count_minute < (target_mpm // 2):
                    # Too slow, decrease slowmode by 1 second
                    new_slowmode = max(current - 1, min_slow)
                else:
                    # Within target, keep current
                    new_slowmode = current

                if new_slowmode != current:
                    try:
                        await channel.edit(slowmode_delay=new_slowmode, reason="Adjusting slowmode based on current channel activity")
                    except discord.Forbidden:
                        print(f"Permission error: Cannot adjust slowmode for {channel.mention}.")
                    except discord.HTTPException as e:
                        print(f"HTTP error: Failed to adjust slowmode for {channel.mention}: {e}")
                    except Exception as e:
                        print(f"Unexpected error: Failed to adjust slowmode for {channel.mention}: {e}")

        # Only send the log every 5 minutes
        self._minute_tick = getattr(self, "_minute_tick", 0) + 1
        if self._minute_tick >= report_every:
            self._minute_tick = 0
            for guild in self.bot.guilds:
                conf = await self.config.guild(guild).all()
                if not conf["enabled"]:
                    continue
                target_mpm = conf["target_msgs_per_min"]
                min_slow = conf["min_slowmode"]
                max_slow = conf["max_slowmode"]
                for cid in conf["channels"]:
                    channel = guild.get_channel(cid)
                    if not channel or not isinstance(channel, discord.TextChannel):
                        continue
                    # Prepare stats for the last 5 minutes
                    stats = list(self._minute_stats[cid])
                    # Pad with zeros if less than 5
                    stats = [0] * (5 - len(stats)) + stats
                    current = channel.slowmode_delay

                    # Collect users seen in the last 5 minutes
                    async with self._lock:
                        cache = self._message_cache[cid]
                        five_min_ago = datetime.now(timezone.utc) - timedelta(minutes=5)
                        user_ids = set()
                        for t, uid in cache:
                            if t > five_min_ago:
                                user_ids.add(uid)
                    # Get user objects and mentions
                    user_mentions = []
                    for uid in user_ids:
                        member = channel.guild.get_member(uid)
                        if member:
                            user_mentions.append(member.mention)
                    # Sort mentions for consistency
                    user_mentions.sort()
                    users_field_value = ", ".join(user_mentions) if user_mentions else "No users seen"

                    embed = discord.Embed(
                        title="Adaptive slowmode is monitoring activity",
                        color=0xfffffe
                    )
                    embed.add_field(
                        name="Channel",
                        value=channel.mention,
                        inline=True
                    )
                    embed.add_field(
                        name="Current slowmode",
                        value=f"{current} {plural(current, 'second')}",
                        inline=True
                    )
                    embed.add_field(
                        name="Target per minute",
                        value=f"{target_mpm} {plural(target_mpm, 'message')}/min",
                        inline=True
                    )
                    # Use dynamic Discord timestamps for each minute
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    minute_lines = []
                    for i, n in zip(range(4, -1, -1), stats):
                        # Each i is 4,3,2,1,0 (oldest to newest)
                        minute_ago_ts = now_ts - (i * 60)
                        # <t:TIMESTAMP:R> gives "x minutes ago"
                        minute_lines.append(f"<t:{minute_ago_ts}:R>: {n} {plural(n, 'msg', 'msgs')}")
                    embed.add_field(
                        name="Last 5 minutes",
                        value="\n".join(minute_lines),
                        inline=False
                    )
                    embed.add_field(
                        name="Users seen recently",
                        value=users_field_value,
                        inline=False
                    )
                    # Add view with buttons for manual adjustment (using current slowmode)
                    view = self.SlowmodeLogView(self, channel, current, min_slow, max_slow)
                    await self._send_log(guild, embed, view=view)

