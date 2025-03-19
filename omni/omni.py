import discord
from redbot.core import commands, Config
import aiohttp
from datetime import timedelta

class Omni(commands.Cog):
    """Cog for moderating messages using OpenAI's omni-moderation endpoint."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(
            moderation_threshold=0.5,
            timeout_duration=0,  # Duration in minutes
            log_channel=None,
            debug_mode=False  # Debug mode toggle
        )
        self.session = aiohttp.ClientSession()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        guild = message.guild
        if not guild:
            return

        api_key = await self.bot.get_shared_api_tokens("openai").get("api_key")
        if not api_key:
            return

        async with self.session.post(
            "https://api.openai.com/v1/moderations",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}"
            },
            json={"input": message.content}
        ) as response:
            if response.status != 200:
                return

            data = await response.json()
            result = data.get("results", [{}])[0]
            flagged = result.get("flagged", False)
            category_scores = result.get("category_scores", {})

            if flagged:
                await self.handle_moderation(message, category_scores)

            # Check if debug mode is enabled
            debug_mode = await self.config.guild(guild).debug_mode()
            if debug_mode:
                await self.log_message(message, category_scores)

    async def handle_moderation(self, message, category_scores):
        guild = message.guild
        timeout_duration = await self.config.guild(guild).timeout_duration()
        log_channel_id = await self.config.guild(guild).log_channel()

        # Delete the message
        await message.delete()

        # Timeout the user if duration is set
        if timeout_duration > 0:
            try:
                await message.author.timeout(timedelta(minutes=timeout_duration), reason="Automated moderation action")
            except discord.Forbidden:
                pass  # Handle cases where the bot doesn't have permission to timeout

        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                embed = discord.Embed(
                    title="Message Moderated",
                    description=f"Message by {message.author.mention} was flagged and deleted.",
                    color=discord.Color.red()
                )
                embed.add_field(name="Content", value=message.content, inline=False)
                for category, score in category_scores.items():
                    embed.add_field(name=category.capitalize(), value=f"{score:.2f}", inline=True)
                await log_channel.send(embed=embed)

    async def log_message(self, message, category_scores):
        guild = message.guild
        log_channel_id = await self.config.guild(guild).log_channel()

        if log_channel_id:
            log_channel = guild.get_channel(log_channel_id)
            if log_channel:
                embed = discord.Embed(
                    title="Message Logged",
                    description=f"Message by {message.author.mention} was logged.",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Content", value=message.content, inline=False)
                for category, score in category_scores.items():
                    embed.add_field(name=category.capitalize(), value=f"{score:.2f}", inline=True)
                await log_channel.send(embed=embed)

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.group()
    async def openaimod(self, ctx):
        """Commands for configuring OpenAI moderation."""
        pass

    @omni.command()
    async def setthreshold(self, ctx, threshold: float):
        """Set the moderation threshold (0 to 1)."""
        if 0 <= threshold <= 1:
            await self.config.guild(ctx.guild).moderation_threshold.set(threshold)
            await ctx.send(f"Moderation threshold set to {threshold}.")
        else:
            await ctx.send("Threshold must be between 0 and 1.")

    @omni.command()
    async def settimeout(self, ctx, duration: int):
        """Set the timeout duration in minutes (0 for no timeout)."""
        if duration >= 0:
            await self.config.guild(ctx.guild).timeout_duration.set(duration)
            await ctx.send(f"Timeout duration set to {duration} minutes.")
        else:
            await ctx.send("Timeout duration must be 0 or greater.")

    @omni.command()
    async def setlogchannel(self, ctx, channel: discord.TextChannel):
        """Set the channel to log moderated messages."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id)
        await ctx.send(f"Log channel set to {channel.mention}.")

    @omni.command()
    @commands.is_owner()
    async def toggledebug(self, ctx):
        """Toggle debug mode to log all messages and their scores."""
        guild = ctx.guild
        current_debug_mode = await self.config.guild(guild).debug_mode()
        new_debug_mode = not current_debug_mode
        await self.config.guild(guild).debug_mode.set(new_debug_mode)
        status = "enabled" if new_debug_mode else "disabled"
        await ctx.send(f"Debug mode {status}.")

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

