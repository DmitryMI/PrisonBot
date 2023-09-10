from discord.sinks import Sink
from discord.commands import context
import discord
import numpy as np
import logging
from discord.ext import commands
import whisper
import wave
import io


RECOGNITION_TIME_CHUNK = 3
BUFFER_CLEAN_TIME = 6

class SpeechRecognitionSink(Sink):
    def __init__(self, bot, ctx, text_callback, whisper_language, *, filters=None):
        Sink.__init__(self, filters=filters)
        self.ctx = ctx
        self.bot = bot
        self.text_callback = text_callback

        if self.text_callback is None:
            logging.error("Text Recognition callback is not defined!")

        self.whisper_language = whisper_language
        self.recognition_timestamps = {}

        self.model = whisper.load_model("base")


    def format_audio(self, audio):
        if self.vc.recording:
            raise Exception(
                "Audio may only be formatted after recording is finished."
            )
        

    def write(self, pcm_bytes, user):
        Sink.write(self, pcm_bytes, user)
        
        for i, user_audio in enumerate(self.get_all_audio()):
            data_chunk_size = self.vc.decoder.SAMPLES_PER_FRAME * self.vc.decoder.SAMPLE_SIZE
            recorded_bytes_length = user_audio.getbuffer().nbytes
            recorded_time = recorded_bytes_length / self.vc.decoder.FRAME_SIZE * self.vc.decoder.FRAME_LENGTH / 1000

            if user not in self.recognition_timestamps:
                self.recognition_timestamps[user] = 0

            if recorded_time - self.recognition_timestamps[user] < RECOGNITION_TIME_CHUNK:
                continue

            logging.info(f"{user} recorded time: {recorded_time}")
            self.recognition_timestamps[user] = recorded_time

            pcm_data_16 = np.frombuffer(user_audio.getbuffer(), np.int16)

            wav_file_path = f'{self.bot.args.downloads_dir}/{user}.wav'

            with wave.open(wav_file_path, 'wb') as wavfile:
                wavfile.setnchannels(self.vc.decoder.CHANNELS)
                wavfile.setsampwidth(4 // self.vc.decoder.CHANNELS)
                wavfile.setframerate(self.vc.decoder.SAMPLING_RATE)
                wavfile.writeframes(pcm_data_16)

            #pcm_data_float = pcm_data_16.flatten().astype(np.float32) / 32768.0 
            
            # result = self.model.transcribe(pcm_data, fp16=False, language=self.whisper_language)
            result = self.model.transcribe(wav_file_path, language=self.whisper_language)
            recognized_text = result["text"]
            self.text_callback(self, user, recognized_text)

            if recorded_time >= BUFFER_CLEAN_TIME:
                stream = io.BytesIO()
                self.audio_data[user] = discord.sinks.AudioData(stream)
                self.recognition_timestamps[user] = 0
