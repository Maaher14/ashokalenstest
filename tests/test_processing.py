import hashlib
import math
import struct
import wave
from pathlib import Path
import pytest
from PIL import Image
from lens.processing import image_edit, audio_edit, mix_audio, inspect, Invalid


def tone(path, seconds=10, amplitude=3000):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(
            b"".join(
                struct.pack(
                    "<h", int(amplitude * math.sin(2 * math.pi * 440 * i / 8000))
                )
                for i in range(int(8000 * seconds))
            )
        )


def test_known_crop_and_original_unchanged(tmp_path):
    source = tmp_path / "in.png"
    out = tmp_path / "out.jpg"
    image = Image.new("RGB", (12, 8), "red")
    image.putpixel((2, 1), (0, 255, 0))
    image.save(source)
    before = hashlib.sha256(source.read_bytes()).digest()
    assert image_edit(source, out, {"crop": [2, 1, 10, 7]})["width"] == 8
    assert Image.open(out).size == (8, 6)
    assert hashlib.sha256(source.read_bytes()).digest() == before
    assert not Image.open(out).getexif()


def test_rotate_resize_filter(tmp_path):
    source = tmp_path / "in.png"
    out = tmp_path / "out.jpg"
    Image.new("RGB", (12, 8), "red").save(source)
    image_edit(source, out, {"rotate": 90, "size": [4, 6], "filter": "greyscale"})
    assert Image.open(out).size == (4, 6)
    r, g, b = Image.open(out).getpixel((0, 0))
    assert r == g == b


def test_audio_trim_silence_and_padding(tmp_path):
    source = tmp_path / "in.wav"
    clip = tmp_path / "clip.mp3"
    mixed = tmp_path / "mix.mp3"
    tone(source)
    meta = inspect(source, "audio")
    result = audio_edit(source, clip, {"start": 2, "end": 6, "volume": 0}, meta)
    assert result["duration"] == 4
    assert abs(inspect(clip, "audio")["duration"] - 4) < 0.1
    mix_audio([clip], mixed, 8)
    assert abs(inspect(mixed, "audio")["duration"] - 8) < 0.1
    from lens.processing import run

    pcm = run(["ffmpeg", "-v", "error", "-i", str(mixed), "-f", "s16le", "-"])
    assert max(abs(n[0]) for n in struct.iter_unpack("<h", pcm)) <= 1
    with pytest.raises(Invalid):
        audio_edit(source, clip, {"start": 6, "end": 2}, meta)


def test_fixed_average_when_short_track_ends(tmp_path):
    from lens.processing import run

    short = tmp_path / "short.wav"
    long = tmp_path / "long.wav"
    out = tmp_path / "mix.mp3"
    tone(short, 1, 0)
    tone(long, 4, 8000)
    mix_audio([short, long], out, 4)
    raw = run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(out),
            "-ar",
            "8000",
            "-ac",
            "1",
            "-f",
            "s16le",
            "-",
        ]
    )
    samples = [s[0] for s in struct.iter_unpack("<h", raw)]

    def rms(segment):
        return (sum(x * x for x in segment) / len(segment)) ** 0.5

    early = rms(samples[4000:6400])
    late = rms(samples[20000:22400])
    reference = tmp_path / "reference.mp3"
    mix_audio([long], reference, 4)
    original = run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(reference),
            "-ar",
            "8000",
            "-ac",
            "1",
            "-f",
            "s16le",
            "-",
        ]
    )
    reference_samples = [s[0] for s in struct.iter_unpack("<h", original)]
    # Compare to the independently encoded single-track amplitude: adding a silent
    # second track halves gain, including after the short track's natural end.
    assert 0.46 < early / rms(reference_samples[4000:6400]) < 0.54
    assert 0.90 < late / early < 1.10
