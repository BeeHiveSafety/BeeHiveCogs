import discord
from redbot.core import commands
from redbot.core.bot import Red
import aiohttp
from typing import Optional

class Transcriber(commands.Cog):
    """Cog to transcribe voice notes using OpenAI."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.openai_api_key: Optional[str] = None

    async def cog_load(self):
        # Load the OpenAI API key from the bot's configuration
        tokens = await self.bot.get_shared_api_tokens("openai")
        self.openai_api_key = tokens.get("api_key")
        if not self.openai_api_key:
            raise ValueError("OpenAI API key is not set. Please set it using the bot's configuration.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # Check if the message contains an attachment and if it's a voice note
        if message.attachments:
            for attachment in message.attachments:
                if attachment.filename.endswith(('.mp3', '.wav', '.ogg', '.flac', '.mp4', '.mpeg', '.mpga', '.m4a', '.webm')):
                    # Download the voice note
                    voice_note = await attachment.read()

                    try:
                        # Send the voice note to OpenAI for transcription
                        transcription = await self.transcribe_voice_note(voice_note, attachment.content_type)
                    except ValueError as e:
                        await message.reply(f"Error during transcription: {str(e)}")
                        return

                    # Create an embed with the transcription
                    embed = discord.Embed(title="", description=transcription, color=0xfffffe)
                    embed.set_author(name=f"{message.author.display_name} said...", icon_url=message.author.avatar.url)
                    embed.set_footer(text="Transcribed using AI, check results for accuracy")

                    # Reply to the message with the transcription
                    await message.reply(embed=embed)

    async def transcribe_voice_note(self, voice_note: bytes, content_type: Optional[str]) -> str:
        # This function should handle sending the voice note to OpenAI and returning the transcription
        url = "https://api.openai.com/v1/audio/transcriptions"
        headers = {
            "Authorization": f"Bearer {self.openai_api_key}"
        }

        data = aiohttp.FormData()
        data.add_field('file', voice_note, filename='audio', content_type=content_type or "audio/mpeg")
        data.add_field('model', 'gpt-4o-transcribe')

        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data) as response:
                if response.status != 200:
                    error_message = await response.text()
                    raise ValueError(f"Failed to transcribe audio: {response.status} - {error_message}")
                result = await response.json()
                return result['text']
