import aiohttp
import asyncio
import discord
import logging
import re
from redbot.core import commands, Config, checks

log = logging.getLogger("red.VirusTotal")

class VirusTotal(commands.Cog):
    """VirusTotal file upload and analysis via Discord"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        self.config.register_guild(auto_scan_enabled=False, submission_history={})
        self.submission_history = {}

    async def initialize(self):
        # Fix: Use .all() safely and don't overwrite config with itself
        for guild in self.bot.guilds:
            guild_data = await self.config.guild(guild).all()
            # Defensive: Only set if present in config
            if "auto_scan_enabled" in guild_data:
                await self.config.guild(guild).auto_scan_enabled.set(guild_data["auto_scan_enabled"])
            if "submission_history" in guild_data:
                await self.config.guild(guild).submission_history.set(guild_data["submission_history"])

    @commands.group(name="virustotal", invoke_without_command=True)
    async def virustotal(self, ctx):
        """VirusTotal is a free online service that analyzes files and URLs to detect viruses, malware, and other security threats."""
        await ctx.send_help(ctx.command)

    @checks.admin_or_permissions(manage_guild=True)
    @virustotal.command(name="autoscan")
    async def toggle_auto_scan(self, ctx):
        """Toggle automatic file scanning on or off"""
        guild = ctx.guild
        auto_scan_enabled = await self.config.guild(guild).auto_scan_enabled()
        new_status = not auto_scan_enabled
        await self.config.guild(guild).auto_scan_enabled.set(new_status)
        status = "enabled" if new_status else "disabled"
        await ctx.send(f"Automatic file scanning has been {status}.")

    @virustotal.command(name="settings")
    async def settings(self, ctx):
        """Show current settings for VirusTotal"""
        guild = ctx.guild
        auto_scan_enabled = await self.config.guild(guild).auto_scan_enabled()
        auto_scan_status = "Enabled" if auto_scan_enabled else "Disabled"
        
        vt_key = await self.bot.get_shared_api_tokens("virustotal")
        api_key_status = ":white_check_mark: Set" if vt_key.get("api_key") else ":x: Missing"
        
        version = "1.2.2"
        last_update = "August 29th, 2024"
        
        embed = discord.Embed(title="VirusTotal settings", colour=discord.Colour(0x394eff))
        embed.add_field(name="Overview", value="\u200b", inline=False)
        embed.add_field(name="Automatic uploads", value=auto_scan_status, inline=True)
        embed.add_field(name="API key", value=api_key_status, inline=True)
        embed.add_field(name="About this cog", value="\u200b", inline=False)
        embed.add_field(name="Version", value=version, inline=True)
        embed.add_field(name="Last updated", value=last_update, inline=True)
        await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Automatically scan files if auto_scan is enabled"""
        # Fix: Ignore bot and webhook messages
        if message.author.bot or message.webhook_id is not None:
            return
        guild = message.guild
        if guild is None:
            return  # Ignore messages not in a guild

        auto_scan_enabled = await self.config.guild(guild).auto_scan_enabled()
        if auto_scan_enabled and message.attachments:
            ctx = await self.bot.get_context(message)
            if ctx.valid:
                await self.silent_scan(ctx, message.attachments)

    def extract_hashes(self, text):
        """Extract potential file hashes from the text"""
        patterns = {
            'sha1': r'\b[0-9a-fA-F]{40}\b',
            'sha256': r'\b[0-9a-fA-F]{64}\b',
            'md5': r'\b[0-9a-fA-F]{32}\b',
            'imphash': r'\b[0-9a-fA-F]{32}\b',
            'ssdeep': r'\b[0-9a-zA-Z/+]{1,64}==\b'
        }
        hashes = []
        for pattern in patterns.values():
            hashes.extend(re.findall(pattern, text))
        return hashes

    async def silent_scan(self, ctx, attachments):
        """Scan files silently and alert only if they're malicious or suspicious"""
        vt_key = await self.bot.get_shared_api_tokens("virustotal")
        if not vt_key.get("api_key"):
            return  # No API key set, silently return

        async with aiohttp.ClientSession() as session:
            for attachment in attachments:
                if attachment.size > 30 * 1024 * 1024:  # 30 MB limit
                    continue  # Skip files that are too large

                try:
                    async with session.get(attachment.url) as response:
                        if response.status != 200:
                            continue  # Skip files that can't be downloaded

                        file_content = await response.read()
                        file_name = attachment.filename

                        # Fix: Use aiohttp's FormData for file upload
                        form = aiohttp.FormData()
                        form.add_field("file", file_content, filename=file_name)

                        async with session.post(
                            "https://www.virustotal.com/api/v3/files",
                            headers={"x-apikey": vt_key["api_key"]},
                            data=form,
                        ) as vt_response:
                            if vt_response.status != 200:
                                continue  # Skip files that can't be uploaded

                            data = await vt_response.json()
                            analysis_id = data.get("data", {}).get("id")
                            if not analysis_id:
                                continue  # Skip files without a valid analysis ID

                            # Check the analysis results
                            while True:
                                await asyncio.sleep(15)  # Wait for the analysis to complete
                                async with session.get(
                                    f"https://www.virustotal.com/api/v3/analyses/{analysis_id}",
                                    headers={"x-apikey": vt_key["api_key"]},
                                ) as result_response:
                                    if result_response.status != 200:
                                        break  # Don't continue forever if error

                                    result_data = await result_response.json()
                                    status = result_data.get("data", {}).get("attributes", {}).get("status")
                                    if status == "completed":
                                        stats = result_data.get("data", {}).get("attributes", {}).get("stats", {})
                                        if stats.get("malicious", 0) > 0 or stats.get("suspicious", 0) > 0:
                                            await ctx.send(f"Alert: The file {file_name} is flagged as malicious or suspicious.")
                                        break
                                    else:
                                        await asyncio.sleep(15)  # Wait a bit before checking again
                except Exception as e:
                    log.error(f"Error in silent_scan: {e}")

    @virustotal.group(name="scan", invoke_without_command=True)
    async def scan(self, ctx):
        """Submit a file or URL to VirusTotal for analysis"""
        await ctx.send_help(ctx.command)

    @scan.command(name="url")
    async def scan_url(self, ctx, file_url: str):
        """Submit a URL to VirusTotal for analysis"""
        async with ctx.typing():
            vt_key = await self.bot.get_shared_api_tokens("virustotal")
            if not vt_key.get("api_key"):
                await self.send_error(ctx, "No VirusTotal API Key set", "Your Red instance doesn't have an API key set for VirusTotal.\n\nUntil you add an API key using `[p]set api`, the VirusTotal API will refuse your requests and this cog won't work.")
                return

            async with aiohttp.ClientSession() as session:
                try:
                    await self.submit_url_for_analysis(ctx, session, vt_key, file_url)
                except (aiohttp.ClientResponseError, ValueError) as e:
                    await self.send_error(ctx, "Failed to submit URL", str(e))
                except asyncio.TimeoutError:
                    await self.send_error(ctx, "Request timed out", "The bot was unable to complete the request due to a timeout.")

    @scan.command(name="file")
    async def scan_file(self, ctx):
        """Submit a file to VirusTotal for analysis"""
        async with ctx.typing():
            vt_key = await self.bot.get_shared_api_tokens("virustotal")
            if not vt_key.get("api_key"):
                await self.send_error(ctx, "No VirusTotal API Key set", "Your Red instance doesn't have an API key set for VirusTotal.\n\nUntil you add an API key using `[p]set api`, the VirusTotal API will refuse your requests and this cog won't work.")
                return

            async with aiohttp.ClientSession() as session:
                try:
                    attachments = ctx.message.attachments
                    if ctx.message.reference and not attachments:
                        try:
                            ref_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                            attachments = ref_message.attachments
                        except Exception:
                            attachments = []
                    if attachments:
                        await self.submit_attachment_for_analysis(ctx, session, vt_key, attachments[0])
                    else:
                        await self.send_error(ctx, "No file provided", "The bot was unable to find content to submit for analysis!\nPlease provide one of the following when using this command:\n- Drag-and-drop a file less than 30mb in size\n- Reply to a message containing a file")
                except (aiohttp.ClientResponseError, ValueError) as e:
                    await self.send_error(ctx, "Failed to submit file", str(e))
                except asyncio.TimeoutError:
                    await self.send_error(ctx, "Request timed out", "The bot was unable to complete the request due to a timeout.")

    async def submit_url_for_analysis(self, ctx, session, vt_key, file_url):
        # Fix: VirusTotal expects url to be sent as x-www-form-urlencoded, not multipart
        data = {"url": file_url}
        headers = {"x-apikey": vt_key["api_key"]}
        async with session.post("https://www.virustotal.com/api/v3/urls", headers=headers, data=data) as response:
            if response.status != 200:
                raise aiohttp.ClientResponseError(response.request_info, response.history, status=response.status, message=f"HTTP error {response.status}", headers=response.headers)
            data = await response.json()
            permalink = data.get("data", {}).get("id")
            if permalink:
                await ctx.send(f"Permalink: https://www.virustotal.com/gui/url/{permalink}")
                await self.check_results(ctx, permalink, ctx.author.id, file_url, None)
            else:
                raise ValueError("No permalink found in the response.")

    async def submit_attachment_for_analysis(self, ctx, session, vt_key, attachment):
        if attachment.size > 30 * 1024 * 1024:  # 30 MB limit
            await self.send_error(ctx, "File too large", "The file you provided exceeds the 30MB size limit for analysis.")
            return
        async with session.get(attachment.url) as response:
            if response.status != 200:
                raise aiohttp.ClientResponseError(response.request_info, response.history, status=response.status, message=f"HTTP error {response.status}", headers=response.headers)
            file_content = await response.read()
            file_name = attachment.filename  # Get the file name from the attachment
            await self.send_info(ctx, "Starting analysis", "This could take a few minutes, please be patient. You'll be mentioned when results are available.")
            # Fix: Use aiohttp's FormData for file upload
            form = aiohttp.FormData()
            form.add_field("file", file_content, filename=file_name)
            async with session.post("https://www.virustotal.com/api/v3/files", headers={"x-apikey": vt_key["api_key"]}, data=form) as response:
                if response.status != 200:
                    raise aiohttp.ClientResponseError(response.request_info, response.history, status=response.status, message=f"HTTP error {response.status}", headers=response.headers)
                data = await response.json()
                analysis_id = data.get("data", {}).get("id")
                if analysis_id:
                    await self.check_results(ctx, analysis_id, ctx.author.id, attachment.url, file_name)
                    # Defensive: Only delete if possible
                    try:
                        await ctx.message.delete()
                    except Exception:
                        pass
                else:
                    raise ValueError("No analysis ID found in the response.")

    async def send_error(self, ctx, title, description):
        # Defensive: Check for ctx.guild and ctx.channel
        guild = getattr(ctx, "guild", None)
        channel = getattr(ctx, "channel", None)
        if guild and channel and channel.permissions_for(guild.me).embed_links:
            embed = discord.Embed(title=f'Error: {title}', description=description, colour=discord.Colour(0xff4545))
            embed.set_thumbnail(url="https://www.beehive.systems/hubfs/Icon%20Packs/Red/close.png")
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"Error: {title}. {description}")

    async def send_info(self, ctx, title, description):
        guild = getattr(ctx, "guild", None)
        channel = getattr(ctx, "channel", None)
        if guild and channel and channel.permissions_for(guild.me).embed_links:
            embed = discord.Embed(title=title, description=description, colour=discord.Colour(0x2BBD8E))
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"{title}. {description}")

    async def check_results(self, ctx, analysis_id, presid, file_url, file_name):
        vt_key = await self.bot.get_shared_api_tokens("virustotal")
        headers = {"x-apikey": vt_key["api_key"]}

        async with aiohttp.ClientSession() as session:
            try:
                # Fix: Always get the latest data after status is completed
                while True:
                    async with session.get(f'https://www.virustotal.com/api/v3/analyses/{analysis_id}', headers=headers) as response:
                        if response.status != 200:
                            raise aiohttp.ClientResponseError(response.request_info, response.history, status=response.status, message=f"HTTP error {response.status}", headers=response.headers)
                        data = await response.json()
                        attributes = data.get("data", {}).get("attributes", {})
                        if attributes.get("status") == "completed":
                            break
                        await asyncio.sleep(3)
                stats = attributes.get("stats", {})
                malicious_count = stats.get("malicious", 0)
                suspicious_count = stats.get("suspicious", 0)
                undetected_count = stats.get("undetected", 0)
                harmless_count = stats.get("harmless", 0)
                failure_count = stats.get("failure", 0)
                unsupported_count = stats.get("type-unsupported", 0)
                # Fix: Get hashes from meta if available, else from attributes
                meta = data.get("meta", {}).get("file_info", {})
                sha256 = meta.get("sha256") or attributes.get("sha256")
                sha1 = meta.get("sha1") or attributes.get("sha1")
                md5 = meta.get("md5") or attributes.get("md5")

                total_count = malicious_count + suspicious_count + undetected_count + harmless_count + failure_count + unsupported_count
                safe_count = harmless_count + undetected_count
                percent = round((malicious_count / total_count) * 100, 2) if total_count > 0 else 0
                if sha256 and sha1 and md5:
                    await self.send_analysis_results(ctx, presid, sha256, sha1, file_name, malicious_count, total_count, percent, safe_count)
                    self.log_submission(ctx.author.id, f"`{file_name or file_url}` - **{malicious_count}/{total_count}** - [View results](https://www.virustotal.com/gui/file/{sha256})")
                else:
                    raise ValueError("Required hash values not found in the analysis response.")
            except (aiohttp.ClientResponseError, ValueError) as e:
                await self.send_error(ctx, "Analysis failed", str(e))
            except asyncio.TimeoutError:
                await self.send_error(ctx, "Request timed out", "The bot was unable to complete the request due to a timeout.")

    async def send_analysis_results(self, ctx, presid, sha256, sha1, file_name, malicious_count, total_count, percent, safe_count):
        content = f"||<@{presid}>||"
        guild = getattr(ctx, "guild", None)
        channel = getattr(ctx, "channel", None)
        can_embed = guild and channel and channel.permissions_for(guild.me).embed_links
        if can_embed:
            embed = discord.Embed()
            if malicious_count >= 11:
                embed.title = "Analysis complete"
                embed.description = f"**{int(percent)}%** of vendors rated this file dangerous! You should avoid this file completely, and delete it from your systems to ensure security."
                embed.color = discord.Colour(0xff4545)
                embed.set_footer(text=f"SHA1 | {sha1}")
            elif 1 < malicious_count < 11:
                embed.title = "Analysis complete"
                embed.description = f"**{int(percent)}%** of vendors rated this file dangerous. While there are malicious ratings available for this file, there aren't many, so this could be a false positive. **You should investigate further before coming to a decision.**"
                embed.color = discord.Colour(0xff9144)
                embed.set_footer(text=f"SHA1 | {sha1}")
            else:
                embed.title = "Analysis complete"
                embed.color = discord.Colour(0x2BBD8E)
                embed.description = f"**{safe_count}** vendors say this file is malware-free"
                embed.set_footer(text=f"{sha1}")
            # Defensive: Only add buttons if supported (discord.py 2.0+)
            try:
                button = discord.ui.Button(label="View results on VirusTotal", url=f"https://www.virustotal.com/gui/file/{sha256}", style=discord.ButtonStyle.url)
                button2 = discord.ui.Button(label="Get a second opinion", url="https://discord.gg/6PbaH6AfvF", style=discord.ButtonStyle.url)
                view = discord.ui.View()
                view.add_item(button)
                view.add_item(button2)
                await ctx.send(content=content, embed=embed, view=view)
            except Exception:
                await ctx.send(content=content, embed=embed)
        else:
            if malicious_count >= 11:
                await ctx.send(f"{content}\nAnalysis complete: **{int(percent)}%** of vendors rated this file dangerous! You should avoid this file completely, and delete it from your systems to ensure security.\nSHA1: {sha1}\nView results on VirusTotal: https://www.virustotal.com/gui/file/{sha256}\nGet a second opinion: https://discord.gg/6PbaH6AfvF")
            elif 1 < malicious_count < 11:
                await ctx.send(f"{content}\nAnalysis complete: **{int(percent)}%** of vendors rated this file dangerous. While there are malicious ratings available for this file, there aren't many, so this could be a false positive. **You should investigate further before coming to a decision.**\nSHA1: {sha1}\nView results on VirusTotal: https://www.virustotal.com/gui/file/{sha256}\nGet a second opinion: https://discord.gg/6PbaH6AfvF")
            else:
                await ctx.send(f"{content}\nAnalysis complete: **{safe_count}** vendors say this file is malware-free\nSHA1: {sha1}\nView results on VirusTotal: https://www.virustotal.com/gui/file/{sha256}\nGet a second opinion: https://discord.gg/6PbaH6AfvF")

    def log_submission(self, user_id, summary):
        if user_id not in self.submission_history:
            self.submission_history[user_id] = []
        self.submission_history[user_id].append(summary)

    @virustotal.command(name="history", aliases=["sh"])
    async def submission_history(self, ctx):
        """View files recently submitted by you"""
        user_id = ctx.author.id
        if user_id in self.submission_history and self.submission_history[user_id]:
            history = "\n".join(self.submission_history[user_id])
            embed = discord.Embed(title="Your recent VirusTotal submissions", description=history, colour=discord.Colour(0x2BBD8E))
        else:
            embed = discord.Embed(title="No recent submissions", description="You have not submitted any files for analysis yet. Submissions reset when the bot restarts.", colour=discord.Colour(0xff4545))
        await ctx.send(embed=embed)


