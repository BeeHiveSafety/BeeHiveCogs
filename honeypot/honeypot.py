import discord
from redbot.core import commands, Config
import typing
import os
from datetime import timedelta

class Honeypot(commands.Cog, name="Honeypot"):
    """Create a channel at the top of the server to attract self bots/scammers and notify/mute/kick/ban them immediately!"""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__()
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
        default_guild = {
            "enabled": False,
            "action": None,
            "logs_channel": None,
            "ping_role": None,
            "honeypot_channel": None,
            "mute_role": None,
            "ban_delete_message_days": 3,
            "scam_stats": {"nitro": 0, "steam": 0, "other": 0},
        }
        self.config.register_guild(**default_guild)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return

        config = await self.config.guild(message.guild).all()
        honeypot_channel_id = config.get("honeypot_channel")
        logs_channel_id = config.get("logs_channel")
        logs_channel = message.guild.get_channel(logs_channel_id) if logs_channel_id else None

        if not config["enabled"] or not honeypot_channel_id or not logs_channel or message.channel.id != honeypot_channel_id:
            return

        if message.author.id in self.bot.owner_ids or message.author.guild_permissions.manage_guild or message.author.top_role >= message.guild.me.top_role:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        # Track scam type based on message content
        scam_type = "other"
        if "nitro" in message.content.lower():
            scam_type = "nitro"
        elif "steam" in message.content.lower():
            scam_type = "steam"

        # Update scam stats
        scam_stats = config["scam_stats"]
        scam_stats[scam_type] += 1
        await self.config.guild(message.guild).scam_stats.set(scam_stats)

        action = config["action"]
        embed = discord.Embed(
            title="Honeypot detected a suspicious user",
            description=f">>> {message.content}",
            color=0xff4545,
            timestamp=message.created_at,
        ).set_author(
            name=f"{message.author.display_name} ({message.author.id})",
            icon_url=message.author.display_avatar.url,
        ).set_thumbnail(url=message.author.display_avatar.url)

        failed = None
        if action:
            try:
                if action == "mute":
                    mute_role_id = config.get("mute_role")
                    mute_role = message.guild.get_role(mute_role_id) if mute_role_id else None
                    if mute_role:
                        await message.author.add_roles(mute_role, reason="Self bot/scammer detected.")
                    else:
                        failed = "**Failed:** The mute role is not set or doesn't exist anymore."
                elif action == "kick":
                    await message.author.kick(reason="Self bot/scammer detected.")
                elif action == "ban":
                    await message.author.ban(reason="Self bot/scammer detected.", delete_message_days=config["ban_delete_message_days"])
                elif action == "timeout":
                    timeout_duration = timedelta(days=7)  # 7 day timeout
                    await message.author.timeout_for(timeout_duration, reason="Self bot/scammer detected.")
            except discord.HTTPException as e:
                failed = f"**Failed:** An error occurred while trying to take action against the member:\n{e}"
            else:
                # Log the action (this is a placeholder for actual logging)
                print(f"Action {action} taken against {message.author}")

            action_result = {
                "mute": "The member has been muted.",
                "kick": "The member has been kicked.",
                "ban": "The member has been banned.",
                "timeout": "The member has been timed out for 7 days."
            }.get(action, "No action taken.")

            embed.add_field(name="Action:", value=failed or action_result, inline=False)

        embed.set_footer(text=message.guild.name, icon_url=message.guild.icon.url)
        ping_role_id = config.get("ping_role")
        ping_role = message.guild.get_role(ping_role_id) if ping_role_id else None
        await logs_channel.send(content=ping_role.mention if ping_role else None, embed=embed)

    @commands.guild_only()
    @commands.admin_or_permissions()
    @commands.group()
    async def honeypot(self, ctx: commands.Context) -> None:
        """Set the honeypot settings. Only administrators can use this command for security reasons."""
        pass

    @commands.admin_or_permissions()
    @honeypot.command()
    async def create(self, ctx: commands.Context) -> None:
        """Create the honeypot channel."""
        honeypot_channel_id = await self.config.guild(ctx.guild).honeypot_channel()
        honeypot_channel = ctx.guild.get_channel(honeypot_channel_id) if honeypot_channel_id else None

        if honeypot_channel:
            await ctx.send(f"The honeypot channel already exists: {honeypot_channel.mention} ({honeypot_channel.id}).")
            return

        honeypot_channel = await ctx.guild.create_text_channel(
            name="honeypot",
            position=0,
            overwrites={
                ctx.guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    read_messages=True,
                    send_messages=True,
                    manage_messages=True,
                    manage_channels=True,
                ),
                ctx.guild.default_role: discord.PermissionOverwrite(
                    view_channel=True, read_messages=True, send_messages=True
                ),
            },
            reason=f"Honeypot channel creation requested by {ctx.author.display_name} ({ctx.author.id}).",
        )

        embed = discord.Embed(
            title="This channel is a security honeypot",
            description="A honeypot is a piece of security tooling used by cybersecurity experts to attract cybercriminals to fake targets. In the same way, this channel is a honeypot. Placed in an obvious place, the instruction is made clear not to speak in this channel. Automated and low quality bots will send messages in this channel, like nitro scams and porn advertisements, not knowing it is a honeypot.",
            color=0xff4545,
        ).add_field(
            name="What not to do?",
            value="- Do not speak in this channel\n- Do not send images in this channel\n- Do not send files in this channel",
            inline=False,
        ).add_field(
            name="What will happen?",
            value="An action will be taken against you as decided by the server owner, which could be anything from a timeout, to an immediate ban.",
            inline=False,
        ).set_footer(text=ctx.guild.name, icon_url=ctx.guild.icon.url).set_image(url="attachment://do_not_post_here.png")

        await honeypot_channel.send(
            embed=embed,
            files=[discord.File(os.path.join(os.path.dirname(__file__), "do_not_post_here.png"))],
        )
        await self.config.guild(ctx.guild).honeypot_channel.set(honeypot_channel.id)
        await ctx.send(
            f"The honeypot channel has been set to {honeypot_channel.mention} ({honeypot_channel.id}). You can now start attracting self bots/scammers!\n"
            "Please make sure to enable the cog and set the logs channel, the action to take, the role to ping (and the mute role) if you haven't already."
        )

    @commands.admin_or_permissions()
    @honeypot.command()
    async def enable(self, ctx: commands.Context) -> None:
        """Enable the honeypot functionality."""
        await self.config.guild(ctx.guild).enabled.set(True)
        await ctx.send("Honeypot functionality has been enabled.")

    @commands.admin_or_permissions()
    @honeypot.command()
    async def disable(self, ctx: commands.Context) -> None:
        """Disable the honeypot functionality."""
        await self.config.guild(ctx.guild).enabled.set(False)
        await ctx.send("Honeypot functionality has been disabled.")

    @commands.admin_or_permissions()
    @honeypot.command()
    async def remove(self, ctx: commands.Context) -> None:
        """Disable the honeypot and delete the honeypot channel."""
        honeypot_channel_id = await self.config.guild(ctx.guild).honeypot_channel()
        honeypot_channel = ctx.guild.get_channel(honeypot_channel_id) if honeypot_channel_id else None

        if honeypot_channel:
            await honeypot_channel.delete(reason=f"Honeypot channel removal requested by {ctx.author.display_name} ({ctx.author.id}).")
            await self.config.guild(ctx.guild).honeypot_channel.set(None)
            await ctx.send("Honeypot channel has been deleted and configuration cleared.")
        else:
            await ctx.send("No honeypot channel to delete.")

        await self.config.guild(ctx.guild).enabled.set(False)

    @commands.admin_or_permissions()
    @honeypot.command()
    async def action(self, ctx: commands.Context, action: str) -> None:
        """Set the action to take when a user is detected in the honeypot channel."""
        if action not in ["mute", "kick", "ban", "timeout"]:
            await ctx.send("Invalid action. Please choose from: mute, kick, ban, timeout.")
            return
        await self.config.guild(ctx.guild).action.set(action)
        await ctx.send(f"Action has been set to {action}.")

    @commands.admin_or_permissions()
    @honeypot.command()
    async def logs(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set the channel where logs will be sent."""
        await self.config.guild(ctx.guild).logs_channel.set(channel.id)
        await ctx.send(f"Logs channel has been set to {channel.mention}.")

    @commands.admin_or_permissions()
    @honeypot.command()
    async def view(self, ctx: commands.Context) -> None:
        """View the current honeypot settings."""
        config = await self.config.guild(ctx.guild).all()
        embed = discord.Embed(title="Current Honeypot Settings", color=0x00ff00)
        embed.add_field(name="Enabled", value=config["enabled"], inline=False)
        embed.add_field(name="Action", value=config["action"] or "Not set", inline=False)
        embed.add_field(name="Logs Channel", value=f"<#{config['logs_channel']}>" if config["logs_channel"] else "Not set", inline=False)
        embed.add_field(name="Ping Role", value=f"<@&{config['ping_role']}>" if config["ping_role"] else "Not set", inline=False)
        embed.add_field(name="Honeypot Channel", value=f"<#{config['honeypot_channel']}>" if config["honeypot_channel"] else "Not set", inline=False)
        embed.add_field(name="Mute Role", value=f"<@&{config['mute_role']}>" if config["mute_role"] else "Not set", inline=False)
        embed.add_field(name="Ban Delete Message Days", value=config["ban_delete_message_days"], inline=False)
        embed.add_field(name="Scam types detected", value=f"Nitro: {config['scam_stats']['nitro']}, Steam: {config['scam_stats']['steam']}, Other: {config['scam_stats']['other']}", inline=False)
        await ctx.send(embed=embed)
