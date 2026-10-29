#!/usr/bin/env python3
"""Build deterministic synthetic footage and sound for the footage evaluations."""

import json
import math
import os
import subprocess
import tempfile
import wave

import numpy as np
from PIL import Image, ImageDraw

RATE = 24000
PHRASES = [
    (0.8, 2.8, "We started with a simple question"),
    (3.4, 5.4, "How can a team stay focused"),
    (6.0, 8.0, "The early sketches were very rough"),
    (8.6, 10.6, "We tested the idea together"),
    (11.2, 12.4, "Um well"),
    (13.2, 15.2, "Sorry can we go again"),
    (16.0, 18.0, "We built Cedar Lantern for teams"),
    (18.6, 20.6, "It keeps shared plans in view"),
    (21.2, 23.2, "A board opens in five seconds"),
    (23.8, 25.8, "Everyone can see the next step"),
    (26.4, 28.0, "That makes planning feel simpler"),
]


def word_timings():
    """Allocate each phrase to word bursts with short gaps."""
    segments = []
    for start, end, text in PHRASES:
        tokens = text.split()
        slot = (end - start) / len(tokens)
        words = []
        for index, token in enumerate(tokens):
            onset = round(start + index * slot, 4)
            offset = round(start + (index + 1) * slot - 0.04, 4)
            words.append({"start": onset, "end": offset, "word": token, "score": 1.0})
        segments.append({"start": start, "end": words[-1]["end"], "text": text, "words": words})
    return segments


def write_wav(path, samples):
    """Write a mono 16-bit PCM signal."""
    pcm = np.asarray(np.clip(samples, -1, 1) * 32767, dtype="<i2")
    with wave.open(path, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(pcm.tobytes())


def make_audio(out, segments):
    """Synthesize voiced harmonic bursts and a deliberately dominant chord bed."""
    voice = np.zeros(40 * RATE, dtype=np.float64)
    for segment in segments:
        for word in segment["words"]:
            first = round(word["start"] * RATE)
            last = round(word["end"] * RATE)
            t = np.arange(last - first) / RATE
            duration = len(t) / RATE
            fade = np.minimum(1, np.minimum(t / 0.008, (duration - t) / 0.008))
            envelope = fade * (0.7 + 0.3 * np.sin(2 * np.pi * 4.5 * t) ** 2)
            signal = np.zeros_like(t)
            for harmonic in range(1, 13):
                frequency = 135 * harmonic
                formants = 0.3 + sum(math.exp(-((frequency - centre) / 220) ** 2)
                                     for centre in (540, 1350, 2400))
                signal += formants * np.sin(2 * np.pi * frequency * t) / harmonic
            voice[first:last] = 0.13 * envelope * signal
    t = np.arange(30 * RATE) / RATE
    bed = sum(np.sin(2 * np.pi * f * t) for f in (220, 277.18, 329.63, 440)) / 4
    rhythm = 0.75 + 0.25 * np.cos(2 * np.pi * 2 * t) ** 8
    music = 0.45 * rhythm * bed
    write_wav(os.path.join(out, "voice.wav"), voice[:30 * RATE])
    write_wav(os.path.join(out, "music.wav"), music)
    return voice


def make_picture(path):
    """Draw an off-centre speaker in a textured room."""
    rng = np.random.default_rng(319)
    small = rng.normal(0, 3, (135, 240, 1))
    base = np.clip(np.array([75, 88, 92]) + small, 0, 255).astype(np.uint8)
    image = Image.fromarray(base, "RGB").resize((1920, 1080), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 160, 650, 700), fill=(95, 107, 107), outline=(130, 139, 136), width=12)
    draw.rectangle((145, 205, 605, 655), fill=(68, 84, 86))
    draw.polygon([(930, 1080), (970, 820), (1080, 750), (1300, 750), (1410, 820), (1450, 1080)],
                 fill=(44, 54, 68))
    draw.rectangle((1140, 685, 1240, 805), fill=(181, 133, 105))
    draw.ellipse((1040, 250, 1340, 740), fill=(190, 145, 115))
    draw.arc((1040, 240, 1340, 510), 180, 355, fill=(44, 39, 35), width=35)
    draw.ellipse((1110, 440, 1130, 460), fill=(32, 31, 29))
    draw.ellipse((1250, 440, 1270, 460), fill=(32, 31, 29))
    draw.line((1150, 610, 1230, 610), fill=(80, 40, 38), width=5)
    image.save(path)


def build(out):
    """Build the fixtures and grader-only answer key."""
    segments = word_timings()
    voice = make_audio(out, segments)
    with open(os.path.join(out, "interview.words.json"), "w", encoding="utf-8") as file:
        json.dump({"segments": segments}, file, indent=2)
    answers = {
        "phrases": [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments],
        "filler_phrase_index_1_based": 5,
        "false_start_phrase_index_1_based": 6,
        "retake_span_seconds": [16.0, 28.0],
        "speaker_box_pixels_xyxy": [930, 240, 1450, 1080],
        "head_box_pixels_xyxy": [1040, 240, 1340, 740],
        "speaker_centre_x_fraction": 1190 / 1920,
        "mouth_box_pixels_xyxy": [1150, 600, 1230, 625],
        "mix_separation_target_db": 10,
        "mix_separation_note": "10 dB RMS voice over music per phrase is a starting target; listening is required.",
        "unducked_voice_minus_music_rms_db_approx": -8.1,
        "music_attenuation_for_target_db_approx": 18.2,
    }
    with open(os.path.join(out, "answers.json"), "w", encoding="utf-8") as file:
        json.dump(answers, file, indent=2)
    with tempfile.TemporaryDirectory() as temp:
        picture = os.path.join(temp, "room.png")
        audio = os.path.join(temp, "voice40.wav")
        make_picture(picture)
        write_wav(audio, voice)
        windows = [f"between(t,{w['start']},{w['end']})" for s in segments for w in s["words"]]
        expression = "+".join(windows)
        filt = (f"drawbox=x=1150:y=600:w=80:h=25:color=0x502826:t=fill:enable='{expression}',"
                "format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709")
        subprocess.run(["ffmpeg", "-hide_banner", "-v", "error", "-y", "-loop", "1", "-framerate", "30",
                        "-i", picture, "-i", audio, "-vf", filt, "-t", "40", "-c:v", "libx264",
                        "-preset", "ultrafast", "-crf", "28", "-c:a", "aac", "-b:a", "96k",
                        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
                        "-movflags", "+faststart", os.path.join(out, "interview.mp4")], check=True)
