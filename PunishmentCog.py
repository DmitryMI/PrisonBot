from datetime import datetime, timedelta
import discord
from discord.ext import commands
import logging
from ContextMap import ContextMap
import asyncio
from SpeechRecognitionSink import SpeechRecognitionSink
from fuzzywuzzy import fuzz
from gtts import gTTS
import io
import os
import os.path
import threading

PUNISHMENT_CHANGE_ROLES = True

# channel_disconnect_lock = threading.Lock()
background_tasks_lock = threading.Lock()

class PunishmentCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sinks_map = ContextMap()
        self.tts_punish_pattern = self.bot.args.tts_punish_pattern
        self.tts_language = self.bot.args.tts_language
        self.whisper_language = self.bot.args.whisper_language
        self.tts_forbidden_pattern = self.bot.args.tts_forbidden_pattern
        self.admin_roles = self.bot.args.admin_roles if self.bot.args.admin_roles else []
        self.admin_usernames = self.bot.args.admin_usernames if self.bot.args.admin_usernames else []

        self.prisoner_role_name = self.bot.args.prisoner_role
        self.prison_channel_name = self.bot.args.prison_channel
        self.prisoner_role_backup_dict = {}
        self.prisoner_escape_phrases = {}
        self.prisoner_nick_backup_dict = {}
        self.prisoner_channel_backup = {}

        self.background_tasks = []

        if not os.path.exists(self.bot.args.downloads_dir):
            os.makedirs(self.bot.args.downloads_dir)

        self.forbidden_lines = []

        if os.path.exists(self.bot.args.config_dir):
            self.read_config()

    def read_config(self):

        forbidden_path = self.bot.args.forbidden_path
        if os.path.exists(forbidden_path):
            logging.info(f"Loading forbidden phrases from '{forbidden_path}'...")
            with open(forbidden_path, "r", encoding="utf-8") as fin:
                lines = fin.readlines()

            for line in lines:
                line_strip = line.strip()
                self.forbidden_lines.append(line_strip)
                logging.debug(f"Forbidden line '{line_strip}' registered")
        else:
            logging.error(f"File {forbidden_path} not found!")
    
    @commands.command()
    async def punish(self, ctx: commands.Context, username, escape_phrase, auto_pardon_time):

        logging.info(f"Punish({username}, {escape_phrase}, {auto_pardon_time}) command issued by {ctx.author.name}")

        has_rights = False
        author = ctx.author

        if not isinstance(author, discord.Member):
            await ctx.send("Can only be used on a Server!")
            return

        author_roles = author.roles

        for author_role in author_roles:
            if author_role.name in self.admin_roles:
                has_rights = True
                break

        if author.name in self.admin_usernames:
            has_rights = True

        if not has_rights:
            await ctx.send("You don't have permition to use this command!")
            return

        auto_pardon_time = float(auto_pardon_time)

        member = ctx.guild.get_member_named(username)

        if not member:
            await ctx.send(f"Member with name {username} not found!")
            return

        prison_channel = self.find_channel_by_name(ctx, self.prison_channel_name)
        
        self.prisoner_role_backup_dict[member.id] = member.roles

        if member.voice:
           self.prisoner_channel_backup[member.id] = member.voice.channel
        else:
           self.prisoner_channel_backup[member.id] = None

        await member.move_to(prison_channel)

        if PUNISHMENT_CHANGE_ROLES:
            prisoner_role = self.find_role_by_name(ctx, self.prisoner_role_name)

            try:
                await member.edit(roles = [prisoner_role])
            except Exception as err:
                logging.error(f"Exception occured during member.edit: {err}")
                await ctx.send(f"Cannot set role {prisoner_role.name} for {member.name}. Reason: {err}")

        if ctx.voice_client:
            await ctx.voice_client.move_to(prison_channel)
        else:
            await prison_channel.connect()

        try:
            self.prisoner_nick_backup_dict[member.id] = member.nick
            nick = self.bot.args.punish_nick_pattern.format(member.name)
            await member.edit(nick=nick)
            logging.info(f"{member.name} nickname changed to {nick}")
        except Exception as err:
            logging.error(f"Failed to set {member.name} nick to {nick}: {err}")
        
        message = f"{member.name} sent to {prison_channel.name} for bad behavior!"

        if escape_phrase:
            message += f"\n{member.name} can say '{escape_phrase}' to escape the prison!"
            self.prisoner_escape_phrases[member.id] = escape_phrase

        if auto_pardon_time:
            message += f"\n{member.name} will be automatically released in {auto_pardon_time} seconds."

            loop = asyncio.get_event_loop()
            task = loop.create_task(self.pardon_after(ctx, auto_pardon_time, [member]))
            task.add_done_callback(self.remove_background_task)

        await ctx.send(message)

        def start_recoring(announcement_error):
            if announcement_error:
                logging.error(f"Announcement playback error: {announcement_error}")
                return

            if ctx not in self.sinks_map:
                sink = SpeechRecognitionSink(self.bot, ctx, self.text_recognition_callback, self.whisper_language)
                self.sinks_map[ctx] = sink
                ctx.voice_client.start_recording(sink, self.recording_stopped_callback, ctx)
                logging.info(f"Recording started in server: {ctx.guild.name}, channel: {ctx.voice_client.channel.name}")

        await self.announce_punishment(ctx, member, escape_phrase, start_recoring)


    def remove_background_task(self, task):
        with background_tasks_lock:
            if task in self.background_tasks:
                self.background_tasks.remove(task)

    def add_background_task(self, task):
        with background_tasks_lock:
            self.background_tasks.append(task)

    async def recording_stopped_callback(self, sink, ctx):
        logging.info(f"Stopped recording for sink {sink} in {ctx.guild.name}")
        

    async def pardon_after(self, ctx, delay, members):
        await asyncio.sleep(delay)
        logging.info("Auto-pardon timeout")

        message = "Prison time of "

        message += ", ".join([member.name for member in members]) + " ended!"

        await ctx.send(message)
        await self.pardon_internal(ctx, members)


    async def text_recognition_callback_async(self, sink, user, text):
        ctx = sink.ctx

        if user not in self.prisoner_escape_phrases:
            logging.info(f"[Text recognition]: {user} ignored due to not having an escape phrase")
            return

        text = text.strip()

        member: discord.Member = ctx.guild.get_member(user)

        if not text:
            logging.info(f"[Text recognition] {member.name}: <empty string>")
            return

        escape_phrase = self.prisoner_escape_phrases[user]

        logging.info(f"[Text recognition] {member.name}: {text}")

        text = text.replace(",", ".")
        text = text.replace("!", ".")
        text = text.replace("?", ".")

        sentences = [sentence.strip() for sentence in text.split(".")]

        sentences.append(text)

        logging.info(f"[Text recognition] {member.name} sentences: {sentences}")

        for sentence in sentences:
            ratio_escape = fuzz.ratio(sentence, escape_phrase)
            if ratio_escape >= 80:
                await ctx.send(f"Prisoner {member.name} said '{sentence}', which is {ratio_escape}% close to {escape_phrase}!")
                await self.pardon_internal(ctx, [member])
                break

            elif ratio_escape >= 50:
                await ctx.send(f"Prisoner {member.name} said '{sentence}', which is {ratio_escape}% close to {escape_phrase}!")

            for forbidden_line in self.forbidden_lines:
                ratio_forbidden = fuzz.ratio(sentence, forbidden_line)
                if ratio_forbidden >= 80:
                    logging.info(f"Forbidden line {forbidden_line} detected in {member.name}'s voice")
                    await ctx.send(f"Prisoner {member.name} said '{sentence}', which is {ratio_forbidden}% close to forbidden {forbidden_line}!")

                    tts_text = self.tts_forbidden_pattern.format(member.name)

                    await self.play_tts(ctx, f"{member.id}-forbidden", tts_text, lambda e: self.forbidden_tts_callback(e, member))
                    # await member.edit(mute=True)
                    
                    break

    async def mute_until_time(self, member, time):
        try:
            # await member.edit(communication_disabled_until=time)
            await member.edit(mute=True)
            logging.info(f"Member {member.name} is muted until {time.timestamp()}")
        except Exception as err:
            logging.error(f"Failed to mute {member.name}: {err}")

    def forbidden_tts_callback(self, e, member):
        logging.info("Forbidden tts finished")
        if e:
            logging.error(f"Forbidden TTSp layback error: {e}")
        duration = self.bot.args.forbidden_mute_duration
        mute_until = datetime.now() + timedelta(seconds=duration)
        task = self.bot.loop.create_task(self.mute_until_time(member, mute_until))
        self.add_background_task(task)
        task.add_done_callback(self.remove_background_task)

    def text_recognition_callback(self, sink, user, text):
        asyncio.run_coroutine_threadsafe(self.text_recognition_callback_async(sink, user, text), self.bot.loop)
        # task = self.bot.loop.create_task(self.text_recognition_callback_async(sink, user, text))
        # self.add_background_task(task)
        # task.add_done_callback(self.remove_background_task)
        

    def find_role_by_id(self, ctx: commands.Context, role_id):
        for role in ctx.guild.roles:
            if role.id == role_id:
                return role
        return None

    def find_role_by_name(self, ctx: commands.Context, role_name):
        for role in ctx.guild.roles:
            if role.name == role_name:
                return role
        return None

    def find_channel_by_name(self, ctx: commands.Context, channel_name):
        for channel in ctx.guild.channels:
            if channel.name == channel_name:
                return channel
        return channel
    
    async def pardon_internal(self, ctx: commands.Context, members: list[discord.Member]):
        prison_channel = self.find_channel_by_name(ctx, self.prison_channel_name)
        prisoner_role = self.find_role_by_name(ctx, self.prisoner_role_name)
        for member in members:

            current_roles = member.roles
            if PUNISHMENT_CHANGE_ROLES and prisoner_role in current_roles and member.id in self.prisoner_role_backup_dict:
                roles = self.prisoner_role_backup_dict[member.id]
                del self.prisoner_role_backup_dict[member.id]
                await member.edit(roles = roles)
                logging.info(f"Roles of {member.name} restored to {roles}")

            if member.voice and member.voice.channel.id == prison_channel.id:
                if member.id in self.prisoner_channel_backup and self.prisoner_channel_backup[member.id]:
                    await member.move_to(self.prisoner_channel_backup[member.id])
                    logging.info(f"Member moved to channel {self.prisoner_channel_backup[member.id]}")
                else:
                    await member.move_to(ctx.author.voice.channel)
                    logging.info(f"Member moved to channel {ctx.author.voice.channel}")

                if member.id in self.prisoner_channel_backup:
                    del self.prisoner_channel_backup[member.id]
            else:
                logging.info(f"Member is not in {prison_channel.name}, they will not be moved to {ctx.author.voice.channel}")

            if member.id in self.prisoner_escape_phrases:
                del self.prisoner_escape_phrases[member.id]

            try:
                if member.id in self.prisoner_nick_backup_dict:
                    nick = self.prisoner_nick_backup_dict[member.id]
                    await member.edit(nick=nick)
                    del self.prisoner_nick_backup_dict[member.id]
                    logging.info(f"{member.name} nickname restored to {nick}")
            except Exception as err:
                logging.error(f"Failed to restore nickname for {member.name}: {err}")

            await ctx.send(f"Pardoned user {member.name}")

        prisoners_in_channel_num = 0

        for member in prison_channel.members:
            if prisoner_role in member.roles:
                prisoners_in_channel_num += 1
                continue
            if member.id in self.prisoner_escape_phrases:
                prisoners_in_channel_num += 1
                continue

        if prisoners_in_channel_num == 0:
            logging.info(f"Nobody is in prison channel {prison_channel.name}. Disconnecting.")

            try:
                if not ctx.voice_client:
                    return

                # if ctx.voice_client and ctx.voice_client.recording:
                #     ctx.voice_client.stop_recording()

                await ctx.voice_client.disconnect()
                del self.sinks_map[ctx]
            except Exception as err:
                logging.error(f"Failed to disconnect from channel {prison_channel.name}. Error: {err}")

        else:
            logging.info(f"Prisoners left in channel {prison_channel.name}: {prisoners_in_channel_num}")

    
    @commands.command()
    async def pardon(self, ctx: commands.Context, *, username):

        members_to_pardon = []
        if username:
            member = ctx.guild.get_member_named(username)
            if not member:
                await ctx.send(f"Member with name {username} not found!")
                return
            members_to_pardon.append(member)
        else:
            for prisoner_id in self.prisoner_role_backup_dict.items():
                member = ctx.guild.get_member(prisoner_id)
                members_to_pardon.append(member)
        
        await self.pardon_internal(ctx, members_to_pardon)

    async def play_tts(self, ctx: commands.Context, filename, text, playback_finished_callback):
        logging.info(f"[TTS]: {text}")

        gtts = gTTS(text=text, lang=self.tts_language, slow=False)
        
        tts_file = f"{self.bot.args.downloads_dir}/{str(filename)}.mp3"
        gtts.save(tts_file)
        
        audio_source = discord.FFmpegPCMAudio(tts_file)

        if not ctx.voice_client.is_playing():
            ctx.voice_client.play(audio_source, after=playback_finished_callback)
        else:
            logging.error("Already playing sound, using Discord's TTS instead")
            await ctx.send(text, tts=True)

    async def announce_punishment(self, ctx: commands.Context, member, escape_phrase, playback_finished_callback):

        text = self.tts_punish_pattern.format(member.name, escape_phrase)

        await self.play_tts(ctx, f"{member.id}-announcement", text, playback_finished_callback)





