import asyncio
from fbchat_muqit import Client, ThreadType

async def main():
    cookies_path = "dane.json"
    # Lets login in Facebook
    bot = await Client.startSession(cookies_path)
    if await bot.isLoggedIn():

        """Lets send a Message to a friend when Client is logged in."""
                                        # put a valid fb user id
        await bot.sendMessage("I'm Online!", "100011178480477", ThreadType.User)
        print("Logged in as", bot.uid)
    # listen to all incoming events
    await bot.listen()

asyncio.run(main())