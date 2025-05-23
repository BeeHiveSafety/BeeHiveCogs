import discord
from redbot.core import commands, Config, app_commands
from datetime import datetime, timedelta, timezone
import aiohttp
import stripe
import tiktoken
import json
import io
import time  # Import time module to measure processing time

class ChatSummary(commands.Cog):
    """Cog to summarize chat activity for users."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=9876543210)
        default_user = {"customer_id": None, "is_afk": False, "afk_since": None, "preferred_model": "gpt-4o"}
        self.config.register_user(**default_user)

    async def _track_stripe_event(self, ctx, customer_id, model_name, event_type, tokens):
        stripe_tokens = await self.bot.get_shared_api_tokens("stripe")
        stripe_key = stripe_tokens.get("api_key") if stripe_tokens else None

        if stripe_key:
            stripe_url = "https://api.stripe.com/v1/billing/meter_events"
            stripe_headers = {
                "Authorization": f"Bearer {stripe_key}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            stripe_payload = {
                "event_name": f"{model_name}_{event_type}",
                "timestamp": int(datetime.now().timestamp()),
                "payload[stripe_customer_id]": customer_id,
                "payload[tokens]": tokens
            }
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(stripe_url, headers=stripe_headers, data=stripe_payload) as stripe_response:
                        if stripe_response.status == 400:
                            error_message = await stripe_response.text()
                            raise Exception(f"Failed to track event with Stripe. Status code: 400, Error: {error_message}")
                        elif stripe_response.status != 200:
                            await ctx.send(f"Failed to track event with Stripe. Status code: {stripe_response.status}", delete_after=10)
                except aiohttp.ClientError as e:
                    await ctx.send(f"Failed to connect to Stripe API: {str(e)}", delete_after=10)

                        
    @commands.group(name="summarizer")
    async def summarizer(self, ctx: commands.Context):
        """Group for summarizer related commands."""
        pass

    @commands.group(name="summarize")
    async def summarize(self, ctx: commands.Context):
        """Group for summarize related commands."""
        pass

    @summarize.command(name="news")
    async def summarize_news(self, ctx: commands.Context):
        """Fetch and summarize news stories based on selected category."""
        openai_tokens = await self.bot.get_shared_api_tokens("openai")
        openai_api_key = openai_tokens.get("api_key") if openai_tokens else None

        if not openai_api_key:
            await ctx.send("OpenAI API key is not set.", delete_after=10)
            return

        user_data = await self.config.user(ctx.author).all()
        customer_id = user_data.get("customer_id")
        preferred_model = user_data.get("preferred_model", "gpt-4o")

        if not customer_id:
            await ctx.send("You must have a customer ID set to use this command.", delete_after=10)
            return

        # Define news categories with descriptions and emojis
        categories = {
            "Technology": {"description": "Latest advancements and updates in technology.", "emoji": "💻"},
            "Sports": {"description": "Recent sports events and news.", "emoji": "🏅"},
            "Politics": {"description": "Current political news and updates.", "emoji": "🏛️"},
            "Health": {"description": "Health-related news and discoveries.", "emoji": "🩺"},
            "Entertainment": {"description": "News from the entertainment industry.", "emoji": "🎬"},
            "Music": {"description": "Updates and news from the music world.", "emoji": "🎵"},
            "Government": {"description": "News related to government actions and policies.", "emoji": "🏢"},
            "Law Enforcement": {"description": "Updates on law enforcement activities.", "emoji": "👮"},
            "Science": {"description": "Recent scientific discoveries and research.", "emoji": "🔬"},
            "Travel": {"description": "News and updates from the travel industry.", "emoji": "✈️"},
            "Education": {"description": "News related to education and learning.", "emoji": "📚"},
            "Environment": {"description": "Updates on environmental issues and news.", "emoji": "🌍"},
            "Business": {"description": "Business news and market trends.", "emoji": "💼"},
            "World": {"description": "Global news and international updates.", "emoji": "🌐"},
            "Fashion": {"description": "Latest trends and news in the fashion industry.", "emoji": "👗"},
            "Food": {"description": "Updates and news about food and culinary arts.", "emoji": "🍽️"},
            "Automotive": {"description": "News and updates from the automotive industry.", "emoji": "🚗"},
            "Real Estate": {"description": "Current trends and news in the real estate market.", "emoji": "🏠"},
            "Aviation": {"description": "Latest news and updates from the aviation industry.", "emoji": "🛩️"},
            "Military": {"description": "News and updates related to military actions and defense.", "emoji": "🪖"},
            "Cryptocurrency": {"description": "News and trends in the cryptocurrency market.", "emoji": "💰"},
            "Weather": {"description": "Updates on weather conditions and forecasts.", "emoji": "☀️"},
            "Gaming": {"description": "Latest news and updates in the gaming industry.", "emoji": "🎮"},
            "Space": {"description": "News about space exploration and astronomy.", "emoji": "🚀"},
            "Finance": {"description": "Updates on financial markets and economic news.", "emoji": "💵"}
        }

        # Create a dropdown for category selection
        class NewsCategoryDropdown(discord.ui.Select):
            def __init__(self, parent_cog, ctx, customer_id, preferred_model, openai_api_key):
                self.parent_cog = parent_cog
                self.ctx = ctx
                self.customer_id = customer_id
                self.preferred_model = preferred_model
                self.openai_api_key = openai_api_key
                options = [discord.SelectOption(label=f"{category}", emoji=f"{info['emoji']}", description=info['description']) for category, info in categories.items()]
                super().__init__(placeholder="25 categories available", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction):
                if interaction.user != self.ctx.author:
                    await interaction.response.send_message("You are not authorized to use this dropdown.", ephemeral=True)
                    return

                await interaction.response.defer()  # Defer the interaction

                selected_category = self.values[0]

                # Create a dropdown for search context size selection
                class SearchContextDropdown(discord.ui.Select):
                    def __init__(self, parent_cog, ctx, customer_id, preferred_model, openai_api_key, selected_category):
                        self.parent_cog = parent_cog
                        self.ctx = ctx
                        self.customer_id = customer_id
                        self.preferred_model = preferred_model
                        self.openai_api_key = openai_api_key
                        self.selected_category = selected_category
                        options = [
                            discord.SelectOption(label="Low", emoji="⚡", description="Least context, lowest cost, fastest response. $0.03/use"),
                            discord.SelectOption(label="Medium", emoji="⚖️", description="Balanced context, cost, and latency. $0.035/use"),
                            discord.SelectOption(label="High", emoji="🧠", description="Most context, highest cost, slower response. $0.05/use")
                        ]
                        super().__init__(placeholder="3 levels available", min_values=1, max_values=1, options=options)

                    async def callback(self, interaction: discord.Interaction):
                        if interaction.user != self.ctx.author:
                            await interaction.response.send_message("You are not authorized to use this dropdown.", ephemeral=True)
                            return

                        await interaction.response.defer()  # Defer the interaction

                        selected_context_size = self.values[0].lower()

                        # Create a dropdown for document generation selection
                        class DocumentGenerationDropdown(discord.ui.Select):
                            def __init__(self, parent_cog, ctx, customer_id, preferred_model, openai_api_key, selected_category, selected_context_size):
                                self.parent_cog = parent_cog
                                self.ctx = ctx
                                self.customer_id = customer_id
                                self.preferred_model = preferred_model
                                self.openai_api_key = openai_api_key
                                self.selected_category = selected_category
                                self.selected_context_size = selected_context_size
                                options = [
                                    discord.SelectOption(label="Yes", emoji="✅", description="Include a .txt of my news summary"),
                                    discord.SelectOption(label="No", emoji="🚫", description="Just send the news in an embed")
                                ]
                                super().__init__(placeholder="Generate a document?", min_values=1, max_values=1, options=options)

                            async def callback(self, interaction: discord.Interaction):
                                if interaction.user != self.ctx.author:
                                    await interaction.response.send_message("You are not authorized to use this dropdown.", ephemeral=True)
                                    return

                                await interaction.response.defer()  # Defer the interaction

                                generate_document = self.values[0].lower() == "yes"

                                # Create buttons for start and cancel
                                class StartCancelButtons(discord.ui.View):
                                    def __init__(self, parent_cog, ctx, customer_id, preferred_model, openai_api_key, selected_category, selected_context_size, generate_document):
                                        super().__init__(timeout=None)
                                        self.parent_cog = parent_cog
                                        self.ctx = ctx
                                        self.customer_id = customer_id
                                        self.preferred_model = preferred_model
                                        self.openai_api_key = openai_api_key
                                        self.selected_category = selected_category
                                        self.selected_context_size = selected_context_size
                                        self.generate_document = generate_document

                                    @discord.ui.button(label="Start", style=discord.ButtonStyle.green)
                                    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
                                        if interaction.user != self.ctx.author:
                                            await interaction.response.send_message("You are not authorized to use this button.", ephemeral=True)
                                            return

                                        await interaction.response.defer()

                                        embed = discord.Embed(
                                            title="Task confirmed",
                                            description="Your task has been dispatched to an agent.\n - This task can take up to 30 seconds to complete, please wait.\n- Work times can vary depending on your preferred model",
                                            color=0x2bbd8e
                                        )
                                        embed.add_field(name="News category", value=self.selected_category, inline=True)
                                        embed.add_field(name="Search intensity", value=self.selected_context_size.capitalize() if self.selected_context_size else "Unknown", inline=True)
                                        embed.add_field(name="Extra copy", value="Yes" if self.generate_document else "No", inline=True)
                                        await interaction.message.edit(embed=embed, view=None)

                                        input_text = f"Give me 5 recent {self.selected_category} news stories as of {datetime.now().strftime('%m-%d-%Y')}"
                                        payload = {
                                            "model": "gpt-4o",
                                            "tools": [{"type": "web_search_preview", "search_context_size": selected_context_size}],
                                            "input": input_text
                                        }

                                        headers = {
                                            "Authorization": f"Bearer {self.openai_api_key}",
                                            "Content-Type": "application/json"
                                        }

                                        async with self.ctx.typing():
                                            start_time_first_call = time.time()  # Start timing the first call
                                            async with aiohttp.ClientSession() as session:
                                                async with session.post("https://api.openai.com/v1/responses", headers=headers, json=payload) as response:
                                                    if response.status == 200:
                                                        data = await response.json()

                                                        # Extract the message content
                                                        message = next((item for item in data["output"] if item["type"] == "message"), None)
                                                        if message:
                                                            content = message["content"][0]
                                                            output_text = content["text"]

                                                            # Tokenize input and output using tiktoken's encoding for the first call
                                                            encoding = tiktoken.get_encoding("o200k_base")
                                                            input_tokens_first_call = len(encoding.encode(input_text))
                                                            output_tokens_first_call = len(encoding.encode(output_text))
                                                            
                                                            # Track stripe event for the first call
                                                            await self.parent_cog._track_stripe_event(self.ctx, self.customer_id, f"gpt-4o-search-preview", "input", input_tokens_first_call)
                                                            await self.parent_cog._track_stripe_event(self.ctx, self.customer_id, f"gpt-4o-search-preview", "output", output_tokens_first_call)

                                                            # Measure time taken for the first call
                                                            time_taken_first_call = time.time() - start_time_first_call

                                                            # Send the output text to the user's preferred model for summarization
                                                            summarize_payload = {
                                                                "model": self.preferred_model,
                                                                "messages": [
                                                                    {
                                                                        "role": "system",
                                                                        "content": "You are a news summarizer. Summarize the following news stories without including any URLs. Add context where possible. Use the format '### Title\n\n> Summary text here'"
                                                                    },
                                                                    {
                                                                        "role": "user",
                                                                        "content": output_text
                                                                    }
                                                                ]
                                                            }

                                                            start_time_second_call = time.time()  # Start timing the second call
                                                            async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=summarize_payload) as summarize_response:
                                                                if summarize_response.status == 200:
                                                                    summarize_data = await summarize_response.json()
                                                                    summary = summarize_data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()

                                                                    # Tokenize input and output using tiktoken's encoding for the second call
                                                                    input_tokens_second_call = len(encoding.encode(output_text))
                                                                    output_tokens_second_call = len(encoding.encode(summary))
                                                                    
                                                                    # Track stripe event for the second call
                                                                    await self.parent_cog._track_stripe_event(self.ctx, self.customer_id, self.preferred_model, "input", input_tokens_second_call)
                                                                    await self.parent_cog._track_stripe_event(self.ctx, self.customer_id, self.preferred_model, "output", output_tokens_second_call)

                                                                    # Measure time taken for the second call
                                                                    time_taken_second_call = time.time() - start_time_second_call

                                                                    # Corrected the payload format and removed incorrect string interpolation
                                                                    stripe_payload = {
                                                                        "event_name": f"gpt-4o-search-preview_{selected_context_size}",
                                                                        "timestamp": int(datetime.now().timestamp()),
                                                                        "payload[stripe_customer_id]": self.customer_id,
                                                                        "payload[uses]": 1
                                                                    }
                                                                    stripe_tokens = await self.parent_cog.bot.get_shared_api_tokens("stripe")
                                                                    stripe_api_key = stripe_tokens.get("api_key") if stripe_tokens else None
                                                                    stripe_headers = {
                                                                        "Authorization": f"Bearer {stripe_api_key}",
                                                                        "Content-Type": "application/x-www-form-urlencoded"
                                                                    }
                                                                    async with session.post("https://api.stripe.com/v1/billing/meter_events", 
                                                                                            headers=stripe_headers, 
                                                                                            data=stripe_payload) as stripe_response:
                                                                        if stripe_response.status != 200:
                                                                            stripe_error_message = await stripe_response.text()
                                                                            await interaction.message.edit(content=f"Failed to log Stripe event. Status code: {stripe_response.status}, Error: {stripe_error_message}", embed=None, view=None)

                                                                    # Create and send embed
                                                                    embed = discord.Embed(
                                                                        title=f"Here's your {self.selected_category.lower()} news summary, curated by AI",
                                                                        description=summary,
                                                                        color=0xfffffe
                                                                    )
                                                                    embed.set_footer(text=f"{time_taken_first_call:.2f}s to search, {time_taken_second_call:.2f}s to summarize. AI can make mistakes, check for errors")
                                                                    
                                                                    # If document generation is requested, create a file
                                                                    if self.generate_document:
                                                                        document_content = f"News Summary for {self.selected_category}\n\n{summary}"
                                                                        document_file = discord.File(io.BytesIO(document_content.encode()), filename="news_summary.txt")
                                                                        await interaction.message.edit(embed=embed, attachments=[document_file], view=None)
                                                                    else:
                                                                        await interaction.message.edit(embed=embed, view=None)
                                                                else:
                                                                    error_message = await summarize_response.text()
                                                                    await interaction.message.edit(content=f"Failed to summarize news stories. Status code: {summarize_response.status}, Error: {error_message}", embed=None, view=None)
                                                    else:
                                                        error_message = await response.text()
                                                        await interaction.message.edit(content=f"Failed to fetch news stories. Status code: {response.status}, Error: {error_message}", embed=None, view=None)

                                    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
                                    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
                                        if interaction.user.id != self.ctx.author.id:
                                            await interaction.response.send_message("You are not authorized to use this button.", ephemeral=True)
                                            return
                                        await interaction.response.defer()  # Defer the interaction
                                        await interaction.message.delete()

                                # Send the start and cancel buttons to the user
                                view = StartCancelButtons(self.parent_cog, self.ctx, self.customer_id, self.preferred_model, self.openai_api_key, self.selected_category, selected_context_size, generate_document)
                                embed = discord.Embed(
                                    title="Review your choices",
                                    description="Make sure everything here looks good, then click **Start**",
                                    color=0xff9144
                                )
                                embed.add_field(name="News category", value=self.selected_category, inline=True)
                                embed.add_field(name="Search intensity", value=selected_context_size.capitalize(), inline=True)
                                embed.add_field(name="Extra copy", value="Yes" if generate_document else "No", inline=True)
                                try:
                                    await interaction.message.edit(embed=embed, view=view)
                                except discord.errors.NotFound:
                                    await self.ctx.send("The interaction has expired. Please try again.", delete_after=10)

                        # Send the document generation dropdown to the user
                        view = discord.ui.View(timeout=None)  # Disable timeout to prevent expiration
                        view.add_item(DocumentGenerationDropdown(self.parent_cog, self.ctx, self.customer_id, self.preferred_model, self.openai_api_key, selected_category, selected_context_size))
                        embed = discord.Embed(
                            title="Do you need an extra text copy of your report?",
                            description="This might be useful if you're going without internet, or need to save the news to use it in a project or other activities.",
                            color=0xff9144
                        )
                        try:
                            await interaction.message.edit(embed=embed, view=view)
                        except discord.errors.NotFound:
                            await self.ctx.send("The interaction has expired. Please try again.", delete_after=10)

                # Send the search context size dropdown to the user
                view = discord.ui.View(timeout=None)  # Disable timeout to prevent expiration
                view.add_item(SearchContextDropdown(self.parent_cog, self.ctx, self.customer_id, self.preferred_model, self.openai_api_key, selected_category))
                embed = discord.Embed(
                    title="Select your search intensity",
                    description="- Less intense searches are cheaper and faster, but may miss information you're interested in\n- More intense searches take longer and cost more, but can be more comprehensive.",
                    color=0xff9144
                )
                embed.set_footer(text="If you're not sure, choose Medium")
                try:
                    await interaction.message.edit(embed=embed, view=view)
                except discord.errors.NotFound:
                    await self.ctx.send("The interaction has expired. Please try again.", delete_after=10)

        # Send the category dropdown to the user
        view = discord.ui.View(timeout=None)  # Disable timeout to prevent expiration
        view.add_item(NewsCategoryDropdown(self, ctx, customer_id, preferred_model, openai_api_key))
        embed = discord.Embed(
            title="Choose a news category",
            description="To get started, select what type of news coverage you're interested in.\n- This helps align the AI to your interests before it starts research on your behalf.\n- If you choose the wrong category, you can cancel before submitting your task.",
            color=0xff9144
        )
        await ctx.send(embed=embed, view=view)
    
    @commands.mod_or_permissions()
    @summarize.command(name="moderation")
    async def summarize_moderation(self, ctx: commands.Context, hours: int = 24):
        """Summarize recent moderation actions from the audit log, including timeouts."""
        try:
            guild = ctx.guild
            if not guild:
                await ctx.send("This command can only be used in a server.", delete_after=10)
                return

            user = ctx.author  # Ensure ctx.author is defined here
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            moderation_actions = []

            async with ctx.typing():
                async for entry in guild.audit_logs(after=cutoff):
                    if entry.action == discord.AuditLogAction.ban:
                        moderation_actions.append({
                            "action": "ban",
                            "user": entry.user.display_name,
                            "target": entry.target.display_name if isinstance(entry.target, discord.Member) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.kick:
                        moderation_actions.append({
                            "action": "kick",
                            "user": entry.user.display_name,
                            "target": entry.target.display_name if isinstance(entry.target, discord.Member) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.member_update:
                        moderation_actions.append({
                            "action": "member_update",
                            "user": entry.user.display_name,
                            "target": entry.target.display_name if isinstance(entry.target, discord.Member) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat(),
                        })
                    elif entry.action == discord.AuditLogAction.unban:
                        moderation_actions.append({
                            "action": "unban",
                            "user": entry.user.display_name,
                            "target": entry.target.display_name if isinstance(entry.target, discord.User) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.message_delete:
                        moderation_actions.append({
                            "action": "message_delete",
                            "user": entry.user.display_name,
                            "target": entry.target.display_name if isinstance(entry.target, discord.Member) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.message_bulk_delete:
                        moderation_actions.append({
                            "action": "bulk_message_delete",
                            "user": entry.user.display_name,
                            "target": "Multiple messages",
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.role_update:
                        moderation_actions.append({
                            "action": "role_update",
                            "user": entry.user.display_name,
                            "target": entry.target.name if isinstance(entry.target, discord.Role) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.member_disconnect:
                        moderation_actions.append({
                            "action": "disconnect_member",
                            "user": entry.user.display_name,
                            "target": entry.target.display_name if isinstance(entry.target, discord.Member) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.automod_rule_create:
                        moderation_actions.append({
                            "action": "automod_rule_create",
                            "user": entry.user.display_name,
                            "target": entry.target.name if isinstance(entry.target, discord.AutoModRule) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.automod_rule_update:
                        moderation_actions.append({
                            "action": "automod_rule_update",
                            "user": entry.user.display_name,
                            "target": entry.target.name if isinstance(entry.target, discord.AutoModRule) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.automod_rule_delete:
                        moderation_actions.append({
                            "action": "automod_rule_delete",
                            "user": entry.user.display_name,
                            "target": entry.target.name if isinstance(entry.target, discord.AutoModRule) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })
                    elif entry.action == discord.AuditLogAction.automod_block_message:
                        moderation_actions.append({
                            "action": "automod_block_message",
                            "user": entry.user.display_name,
                            "target": entry.target.display_name if isinstance(entry.target, discord.Member) else str(entry.target),
                            "reason": entry.reason or "No reason found",
                            "timestamp": entry.created_at.isoformat()
                        })

                if not moderation_actions:
                    await ctx.send("No moderation actions found in the specified time frame.", delete_after=10)
                    return

                # Prepare the content for summarization
                actions_content = "\n".join(
                    f"{action['timestamp']}: {action['user']} performed {action['action']} on {action['target']} for '{action['reason']}'"
                    for action in moderation_actions
                )

                # Use OpenAI to summarize the actions
                tokens = await self.bot.get_shared_api_tokens("openai")
                openai_key = tokens.get("api_key") if tokens else None
                if not openai_key:
                    await ctx.send("OpenAI API key is not set.", delete_after=10)
                    return

                # Determine model based on user preference
                user_data = await self.config.user(user).all()
                customer_id = user_data.get("customer_id")
                preferred_model = user_data.get("preferred_model", "gpt-4o")
                model = preferred_model if customer_id else "gpt-4o-mini"

                # Calculate token usage
                encoding = tiktoken.encoding_for_model(model)
                input_tokens = len(encoding.encode(actions_content))

                async with aiohttp.ClientSession() as session:
                    headers = {
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": model,
                        "messages": [
                            {
                                "role": "system",
                                "content": "You are a moderation summary generator. Use bulletpoints. Don't use titles. Only connect events if they happen within an ongoing time span of each other."
                            },
                            {
                                "role": "user",
                                "content": f"Summarize the following moderation history: {actions_content}"
                            }
                        ]
                    }
                    async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload) as response:
                        if response.status == 200:
                            data = await response.json()
                            summary = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                            output_tokens = len(encoding.encode(summary))
                            embed = discord.Embed(
                                title="AI moderation summary",
                                description=summary,
                                color=0xfffffe
                            )
                            await ctx.send(embed=embed)
                            # Track stripe event if customer_id is present
                            if customer_id:
                                await self._track_stripe_event(ctx, customer_id, model, "input", input_tokens)
                                await self._track_stripe_event(ctx, customer_id, model, "output", output_tokens)
                        else:
                            await ctx.send(f"Failed to summarize moderation actions. Status code: {response.status}", delete_after=10)

        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}", delete_after=10)

    @summarize.command(name="server")
    async def summarize_server(self, ctx: commands.Context):
        """Summarize information about the server using AI."""
        try:
            guild = ctx.guild
            if not guild:
                await ctx.send("This command can only be used in a server.", delete_after=10)
                return

            # Collect server information
            server_info = {
                "name": guild.name,
                "id": guild.id,
                "member_count": guild.member_count,
                "owner": guild.owner.display_name if guild.owner else "Unknown",
                "created_at": guild.created_at.isoformat(),
                "activity_statuses": {
                    "online": sum(1 for member in guild.members if not member.bot and member.status == discord.Status.online),
                    "idle": sum(1 for member in guild.members if not member.bot and member.status == discord.Status.idle),
                    "dnd": sum(1 for member in guild.members if not member.bot and member.status == discord.Status.dnd),
                    "offline": sum(1 for member in guild.members if not member.bot and member.status == discord.Status.offline)
                },
                "games_playing": [activity.name for member in guild.members if not member.bot for activity in member.activities if isinstance(activity, discord.Game)],
                "songs_listening": [activity.title for member in guild.members if not member.bot for activity in member.activities if isinstance(activity, discord.Spotify)]
            }

            # Prepare the content for summarization
            server_content = "\n".join(f"{key}: {value}" for key, value in server_info.items())

            # Use OpenAI to summarize the server information
            tokens = await self.bot.get_shared_api_tokens("openai")
            openai_key = tokens.get("api_key") if tokens else None
            if not openai_key:
                await ctx.send("OpenAI API key is not set.", delete_after=10)
                return

            # Determine model based on user preference
            user = ctx.author
            user_data = await self.config.user(user).all()
            customer_id = user_data.get("customer_id")
            preferred_model = user_data.get("preferred_model", "gpt-4o")
            model = preferred_model if customer_id else "gpt-4o-mini"

            # Calculate token usage
            encoding = tiktoken.encoding_for_model(model)
            input_tokens = len(encoding.encode(server_content))

            async with aiohttp.ClientSession() as session:
                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a Discord server information summary generator. Reply in a single conversational paragraph with basic language. Use Discord native timestamps when referring to times which are formatted as <t:UNIXTIME:d>."
                        },
                        {
                            "role": "user",
                            "content": f"Summarize the following server information: {server_content}"
                        }
                    ],
                    "temperature": 1.0
                }
                async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload) as response:
                    if response.status == 200:
                        data = await response.json()
                        summary = data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                        output_tokens = len(encoding.encode(summary))
                        embed = discord.Embed(
                            title="AI summary of this server",
                            description=summary,
                            color=0xfffffe
                        )
                        await ctx.send(embed=embed)
                        # Track stripe event if customer_id is present
                        if customer_id:
                            await self._track_stripe_event(ctx, customer_id, model, "input", input_tokens)
                            await self._track_stripe_event(ctx, customer_id, model, "output", output_tokens)
                    else:
                        await ctx.send(f"Failed to summarize server information. Status code: {response.status}", delete_after=10)

        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}", delete_after=10)













    @summarize.command(name="recent")
    async def chat_summary(self, ctx: commands.Context, afk_only: bool = False, target_user: discord.User = None):
        """Summarize recent channel activity or only messages missed while AFK."""
        try:
            guild = ctx.guild
            if not guild:
                await ctx.send("This command can only be used in a server.", delete_after=10)
                return

            user = target_user or ctx.author
            user_data = await self.config.user(user).all()
            customer_id = user_data.get("customer_id")
            preferred_model = user_data.get("preferred_model", "gpt-4o")
            model = preferred_model if customer_id else "gpt-4o-mini"
            hours = 8 if customer_id else 2

            if afk_only and user_data.get("afk_since"):
                cutoff = datetime.fromisoformat(user_data["afk_since"])
            else:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

            recent_messages = []
            mentions = []

            channel = ctx.channel
            if not channel:
                await ctx.send("This command can only be used in a text channel.", delete_after=10)
                return

            async with ctx.typing():
                async for message in channel.history(limit=1000, after=cutoff):
                    if not message.author.bot:
                        recent_messages.append({
                            "author": message.author.display_name,
                            "content": message.content,
                            "timestamp": message.created_at.isoformat()
                        })
                        if user in message.mentions:
                            is_reply = False
                            if message.reference and message.reference.resolved:
                                resolved_message = message.reference.resolved
                                if isinstance(resolved_message, discord.Message) and resolved_message.author == user:
                                    is_reply = True
                            mentions.append({
                                "author": message.author.display_name,
                                "timestamp": message.created_at,
                                "jump_url": message.jump_url,
                                "is_reply": is_reply
                            })

                messages_content = "\n".join(f"{msg['author']}: {msg['content']}" for msg in recent_messages)
                tokens = await self.bot.get_shared_api_tokens("openai")
                openai_key = tokens.get("api_key") if tokens else None

                ai_summary, input_tokens, output_tokens = await self._generate_ai_summary(openai_key, messages_content, customer_id, model)
                mention_summary = self._generate_mention_summary(mentions)
                await self._send_summary_embed(ctx, ai_summary, mention_summary, customer_id, user)

                if openai_key and customer_id:
                    await self._track_stripe_event(ctx, customer_id, model, "input", input_tokens)
                    await self._track_stripe_event(ctx, customer_id, model, "output", output_tokens)

        except Exception as e:
            await ctx.send(f"An error occurred: {str(e)}", delete_after=10)

    async def _generate_ai_summary(self, openai_key, messages_content, customer_id, model):
        openai_url = "https://api.openai.com/v1/chat/completions"
        if openai_key:
            headers = {
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json"
            }
            messages = [
                {"role": "system", "content": "You are a chat summary generator. Use title-less bulletpoints where appropriate. Include time references like NUM hours ago or NUM minutes ago so users understand how long has passed inbetween certain pieces of activity."},
                {"role": "user", "content": f"Summarize the following chat messages: {messages_content}"}
            ]
            encoding = tiktoken.encoding_for_model(model)
            input_tokens = len(encoding.encode(messages_content))
            openai_payload = {
                "model": model,
                "messages": messages,
                "temperature": 1.0
            }
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.post(openai_url, headers=headers, json=openai_payload) as openai_response:
                        if openai_response.status == 200:
                            openai_data = await openai_response.json()
                            summary = openai_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                            output_tokens = len(encoding.encode(summary))
                            return summary, input_tokens, output_tokens
                        else:
                            return f"Failed to generate summary from OpenAI. Status code: {openai_response.status}", 0, 0
                except aiohttp.ClientError as e:
                    return f"Failed to connect to OpenAI API: {str(e)}", 0, 0
        else:
            return "OpenAI API key not configured.", 0, 0

    def _generate_mention_summary(self, mentions):
        if not mentions:
            return "No mentions in the recent messages."
        # Sort mentions by timestamp in descending order and take the last 5
        recent_mentions = sorted(mentions, key=lambda x: x['timestamp'], reverse=True)[:5]
        return "\n".join(
            f"- **{mention['author']}** {'replied to you' if mention['is_reply'] else 'mentioned you'} *<t:{int(mention['timestamp'].timestamp())}:R>* **[Jump]({mention['jump_url']})**"
            for mention in recent_mentions
        )

    async def _send_summary_embed(self, ctx, ai_summary, mention_summary, customer_id, user):
        embed = discord.Embed(
            title="Here's your conversation summary",
            description=ai_summary or "No recent messages.",
            color=0xfffffe
        )
        embed.add_field(name="Activity you may have missed", value=mention_summary, inline=False)
        if not customer_id:
            embed.set_footer(text="You're using the free version of BeeHive's AI summarizer. Upgrade for improved speed, intelligence, and functionality.")
        else:
            embed.set_footer(text="You're powered up with premium AI models and extended discussion context.")
        
        try:
            await user.send(embed=embed)
            embed = discord.Embed(
                title="AI summary sent",
                description=":mailbox_with_mail: Check your **Direct Messages** for more details",
                color=0xfffffe
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send(embed=embed)

    @summarizer.command(name="id")
    @commands.is_owner()
    async def manage_customer_id(self, ctx: commands.Context, user: discord.User, customer_id: str = None):
        """Set or clear a customer's ID for a user globally."""
        
        if customer_id is not None:
            await self.config.user(user).customer_id.set(customer_id)
            await ctx.send(f"Customer ID for {user.name} has been set to {customer_id}.")
        else:
            await self.config.user(user).customer_id.clear()
            await ctx.send(f"Customer ID for {user.name} has been cleared.")

    @summarizer.command(name="profile")
    async def view_profile(self, ctx: commands.Context):
        """View your own summarizer profile."""
        user = ctx.author
        user_data = await self.config.user(user).all()
        customer_id = user_data.get("customer_id", "Not set")
        preferred_model = user_data.get("preferred_model", "gpt-4o")

        embed = discord.Embed(
            title=f"{user.display_name}'s summarizer profile",
            color=0xfffffe
        )

        if isinstance(ctx.channel, discord.DMChannel):
            embed.add_field(name="Customer ID", value=customer_id, inline=False)
            embed.add_field(name="Preferred Model", value=preferred_model, inline=False)
        else:
            embed.add_field(name="Customer ID", value="Hidden", inline=False)
            embed.add_field(name="Preferred Model", value=preferred_model, inline=False)

        if customer_id != "Not set":
            stripe_tokens = await self.bot.get_shared_api_tokens("stripe")
            stripe_key = stripe_tokens.get("api_key") if stripe_tokens else None

            if stripe_key:
                async def generate_billing_link(interaction):
                    if interaction.user != ctx.author:
                        await interaction.response.send_message("You're not the customer, nor are you allowed to access their billing portal. Please see https://en.wikipedia.org/wiki/Computer_Fraud_and_Abuse_Act to know why you're not allowed to do this.", ephemeral=True)
                        return

                    async with aiohttp.ClientSession() as session:
                        try:
                            stripe_url = "https://api.stripe.com/v1/billing_portal/sessions"
                            stripe_headers = {
                                "Authorization": f"Bearer {stripe_key}",
                                "Content-Type": "application/x-www-form-urlencoded"
                            }
                            stripe_payload = {
                                "customer": customer_id,
                                "return_url": ctx.channel.jump_url
                            }
                            async with session.post(stripe_url, headers=stripe_headers, data=stripe_payload) as stripe_response:
                                if stripe_response.status == 200:
                                    response_data = await stripe_response.json()
                                    login_url = response_data.get("url")
                                    if login_url:
                                        await interaction.response.send_message(f"[Click here to manage your billing](<{login_url}>)\n\n# :octagonal_sign: This link will automatically sign you in - **don't share it with others no matter what**.", ephemeral=True)
                                else:
                                    await interaction.response.send_message(f"Failed to generate billing portal link. Status code: {stripe_response.status}", ephemeral=True)
                        except aiohttp.ClientError as e:
                            await interaction.response.send_message(f"Failed to connect to Stripe API: {str(e)}", ephemeral=True)

                view = discord.ui.View(timeout=30)
                button = discord.ui.Button(label="🔒 Quick login", style=discord.ButtonStyle.gray)
                button.callback = generate_billing_link
                view.add_item(button)
                await ctx.send(embed=embed, view=view)
        else:
            await ctx.send(embed=embed)

    @summarizer.command(name="model")
    async def set_preferred_model(self, ctx: commands.Context):
        """Set your preferred AI model for summarization."""
        user = ctx.author
        user_data = await self.config.user(user).all()
        customer_id = user_data.get("customer_id")

        if not customer_id:
            await ctx.send("You must have a customer ID set to use this command.", delete_after=10)
            return

        # Define valid models with descriptions and emojis
        model_details = {
            "gpt-3.5-turbo": ("💬", "$0.0000005 per token in / $0.0000015 per token out"),
            "gpt-4o-mini": ("💬", "$0.00000015 per token in / $0.0000006 per token out"),
            "o3-mini": ("🧠", "$0.0000011 per token in / $0.0000044 per token out"),
            "gpt-4o": ("💬", "$0.0000025 per token in / $0.00001 per token out"),
            "chatgpt-4o-latest": ("💬", "$0.000005 per token in / $0.000015 per token out"),
            "gpt-4-turbo": ("💬", "$0.00001 per token in / $0.00003 per token out"),
            "o1": ("🧠", "$0.000015 per token in / $0.00006 per token out"),
            "gpt-4": ("💬", "$0.00003 per token in / $0.00006 per token out"),
            "gpt-4.1": ("💬", "$0.000002 per token in / $0.000008 per token out"),
        }

        # Create a dropdown menu for model selection
        class ModelDropdown(discord.ui.Select):
            def __init__(self, config, user, embed_message):
                self.config = config
                self.user = user
                self.embed_message = embed_message
                options = [
                    discord.SelectOption(label=model, description=description, emoji=emoji)
                    for model, (emoji, description) in model_details.items()
                ]
                super().__init__(placeholder="Choose your preferred model...", min_values=1, max_values=1, options=options)

            async def callback(self, interaction: discord.Interaction):
                selected_model = self.values[0]
                await self.set_model(interaction, selected_model)

            async def set_model(self, interaction: discord.Interaction, model: str):
                await self.config.user(self.user).preferred_model.set(model)
                try:
                    await interaction.response.defer()
                except discord.errors.NotFound:
                    await interaction.followup.send("Interaction not found. Please try again.", ephemeral=True)
                    return
                # Update the original embed with the selected model and pricing
                embed = self.embed_message.embeds[0]
                emoji, pricing = model_details[model]
                embed.add_field(name="Model selected", value=f"{emoji} {model}\n{pricing}", inline=False)
                await self.embed_message.edit(embed=embed)

        class ModelDropdownView(discord.ui.View):
            def __init__(self, config, user, embed_message):
                super().__init__(timeout=30)
                self.add_item(ModelDropdown(config, user, embed_message))

        # Send the dropdown view to the user
        embed = discord.Embed(
            title="Select a preferred model",
            description="Adjusting your model can change your experience drastically.\n\n- Some models are very intelligent and have reasoning built-in, but can be more expensive to use\n- Other models may be cheaper and faster, but lack an up-to-date knowledge window or the ability to reason, think, or deduce.\n- The variable intelligence of each AI model can impact the outputs of all summarization tool use drastically.\n\n[Click here to learn more about each model's capabilities](<https://platform.openai.com/docs/models>)\n\n- Models labeled with a \"💬\" are chat-first models\n- Models labeled with a \"🧠\" are reasoning/thinking models.\n- Models are sorted from cheapest to most expensive based on averaged input and output per token per model.",
            color=0xfffffe
        )
        embed_message = await ctx.send(embed=embed)
        view = ModelDropdownView(self.config, user, embed_message)
        await embed_message.edit(view=view)

    @summarizer.command(name="tokens")
    async def summarizer_tokens(self, ctx: commands.Context):
        """Explain how words are converted into tokens and provide examples."""

        # Define sentences to tokenize
        sentences = [
            "The quick brown fox jumped over the lazy dog",
            "Before you get home, can you stop at the grocery store and pick up a can of corn for dinner?",
            "I wonder how the stock markets are doing, DGVXX was up at lunch and has been returning solid investments over the last 3 dividends. This is a buy recommendation for sure."
        ]

        # Initialize the encoding
        try:
            encoding = tiktoken.get_encoding("o200k_base")
        except Exception as e:
            await ctx.send(f"Failed to initialize encoding: {e}")
            return

        # Tokenize each sentence and prepare the token chains
        token_chains = []
        for sentence in sentences:
            try:
                tokens = encoding.encode(sentence)
                token_chains.append((sentence, tokens, len(tokens)))
            except Exception as e:
                await ctx.send(f"Failed to tokenize sentence: {sentence}. Error: {e}")
                return

        # Create the description with real token chains
        description = (
            "AI and Natural Language models process text by breaking it down into smaller units called tokens. The AI understands the value of words by their tokenized values to know what the word is - the AI itself does not read your English as English. "
            "A token can be as short as one character or as long as one word. "
            "The number of tokens affects the cost and speed of processing text.\n\n"
            "Here are 3 examples to help you understand how language is processed\n\n"
        )
        for sentence, tokens, token_count in token_chains:
            description += f"- The sentence ```{sentence}``` is tokenized as ```{tokens}``` with a total of {token_count} tokens.\n\n"

        description += (
            "\nUnderstanding how text is tokenized and transformed as input and output can help you estimate the cost and efficiency of using different AI models for different tasks."
        )

        embed = discord.Embed(
            title="What tokens are and how they work",
            description=description,
            color=0xfffffe
        )
        embed.set_footer(text="For more detailed information, refer to the OpenAI documentation.")
        await ctx.send(embed=embed)


    @commands.command(name="away")
    async def set_away(self, ctx: commands.Context):
        """Set your status to away."""
        await self.config.user(ctx.author).is_afk.set(True)
        await self.config.user(ctx.author).afk_since.set(datetime.now(timezone.utc).isoformat())
        embed = discord.Embed(
            title=f"See you later, {ctx.author.display_name}!",
            description=f"You're now **away**.\nYou'll get an AI-powered summary of what you've missed when you come back.",
            color=0xfffffe
        )
        embed.set_footer(text="You'll automatically have your away status cleared if you type in a channel while marked away.")
        async with ctx.typing():
            await ctx.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_without_command(self, message: discord.Message):
        if message.author.bot:
            return

        user_data = await self.config.user(message.author).all()
        if user_data.get("is_afk"):
            await self.config.user(message.author).is_afk.set(False)
            embed = discord.Embed(
                title="Welcome back",
                description=f":sparkles: Generating AI summary",
                color=0xfffffe
            )
            await message.channel.send(embed=embed)
            ctx = await self.bot.get_context(message)
            await self.chat_summary(ctx, afk_only=True, target_user=message.author)

        for user in message.mentions:
            if user.bot:
                continue
            user_data = await self.config.user(user).all()
            if user_data.get("is_afk"):
                embed = discord.Embed(
                    title="This user's away right now",
                    description=f"**{user.display_name} is currently AFK and may not respond immediately.**\nThey'll get a summary of what they missed when they return.",
                    color=discord.Color.orange()
                )
                await message.channel.send(embed=embed)
