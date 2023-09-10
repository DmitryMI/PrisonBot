import discord
import argparse
import os
import os.path
import logging
import logging.handlers
import asyncio
from discord.ext import commands
import PunishmentCog

background_tasks = []

class PrisonBotClient(commands.Bot):

    def __init__(self, intents, args):
        super().__init__(command_prefix=commands.when_mentioned_or(args.command_prefix), intents=intents)
        self.args = args

    async def on_ready(self):
        logging.info(f'Logged on as {self.user}')

    async def on_message(self, message):
        logging.info(f'Message from {message.author}: {message.content}')

        # Allows the bot to process commands.
        await self.process_commands(message)

@commands.command()
async def prisonbot_echo(ctx, msg):
    """Adds two numbers together."""
    await ctx.send(f"PrisonBot echo: {msg}")


def create_bot(args):
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True

    bot = PrisonBotClient(intents, args)

    bot.add_command(prisonbot_echo)
    bot.add_cog(PunishmentCog.PunishmentCog(bot))

    return bot

def configure_logging(logs_dir="logs", log_level = logging.INFO):
    log_file = os.path.join(logs_dir, "dbot.log")

    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)

    dt_fmt = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter('[{asctime}] [{levelname:<8}] [{threadName}({thread})] {name}: {message}', dt_fmt, style='{')

    handler_console = logging.StreamHandler()
    handler_console.setFormatter(formatter)
    handler_rotating = logging.handlers.RotatingFileHandler(
        filename=log_file,
        encoding='utf-8',
        maxBytes=32 * 1024 * 1024,  # 32 MiB
        backupCount=5,  # Rotate through 5 files
    )
    handler_rotating.setFormatter(formatter)

    # Setup default logger
    logger_default = logging.getLogger()
    logger_default.setLevel(log_level)
    logger_default.addHandler(handler_rotating)
    logger_default.addHandler(handler_console)


async def main():
    parser = argparse.ArgumentParser(
                    prog='PrisonBot',
                    description='Discord Bot for punishing guild members',
                    epilog='By Dmitriy')

    #parser.add_argument('filename')           # positional argument
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--token', help="API Token for the bot. Must be kept in secret!")
    group.add_argument('--token_file', help="API Token for the bot stored in a text file. The token must be kept in secret!")

    parser.add_argument("--command_prefix", help="Commands prefix", default="$")
    parser.add_argument("--log_dir", help= "Directory for log files")
    parser.add_argument("--config_dir", help= "Directory for config files", default="config")
    parser.add_argument("--downloads_dir", help = "Directory for downloads", default = "downloads")
    parser.add_argument("--prison_channel", help="Prison channel name", default="Prison")
    parser.add_argument("--prisoner_role", help="Prisoner role name", default="Prisoner")
    parser.add_argument("--admin_roles", help="Admin role name", nargs="*")
    parser.add_argument("--admin_usernames", help="Admin nickname", nargs="*")
    parser.add_argument("--announcement_pattern", help="Announcement pattern for imprisonment", type=str, default="{}, say {}")
    parser.add_argument("--announcement_language", help="Announcement language for imprisonment", type=str, default="en")

    args = parser.parse_args()

    configure_logging()

    api_token = None

    if args.token is not None:
        api_token = args.token
    else:
        token_file_path = args.token_file
        if not os.path.exists(token_file_path):
            logging.error(f"File {token_file_path} does not exist!")
            return
        with open(token_file_path, 'r') as fin:
            api_token = fin.read()
    
    bot = create_bot(args)

    await bot.start(api_token)


if __name__ == "__main__":

    asyncio.run(main())