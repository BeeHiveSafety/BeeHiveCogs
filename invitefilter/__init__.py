from .invitefilter import InviteFilter

async def setup(bot):
    cog = InviteFilter(bot)
    await bot.add_cog(cog)
