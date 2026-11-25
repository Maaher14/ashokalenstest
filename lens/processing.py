"""Bounded Pillow and FFmpeg operations; originals are never modified."""

import json
import math
import subprocess
import warnings
from pathlib import Path
from PIL import Image, ImageOps, ImageEnhance, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 20_000_000


class Invalid(ValueError):
    pass


def number(value, name, minimum, maximum):
    if isinstance(value, bool):
        raise Invalid(f"{name} must be a number.")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise Invalid(f"{name} must be a number.")
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise Invalid(f"{name} must be between {minimum:g} and {maximum:g}.")
    return result


def run(args):
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=60).stdout
    except subprocess.TimeoutExpired:
        raise Invalid("Processing took too long. Try a smaller file and retry.")
    except subprocess.CalledProcessError:
        raise Invalid("This media could not be decoded or processed.")


def inspect(path, kind):
    if kind == "image":
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(path) as source:
                    if (
                        source.format not in ("JPEG", "PNG")
                        or getattr(source, "n_frames", 1) != 1
                    ):
                        raise Invalid("Use a single JPEG or PNG image.")
                    image = ImageOps.exif_transpose(source)
                    if image.width * image.height > 20_000_000:
                        raise Invalid("Images must be at most 20 megapixels.")
                    image.load()
                    return {
                        "width": image.width,
                        "height": image.height,
                        "mime": (
                            "image/jpeg" if source.format == "JPEG" else "image/png"
                        ),
                    }
        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ):
            raise Invalid("Use a valid JPEG/PNG image up to 20 megapixels.")
    result = json.loads(
        run(
            [
                "ffprobe",
                "-protocol_whitelist",
                "file,pipe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(path),
            ]
        )
    )
    streams = result.get("streams", [])
    if len(streams) != 1 or streams[0].get("codec_type") != "audio":
        raise Invalid("Use an audio-only MP3 or WAV file.")
    fmt = result.get("format", {}).get("format_name", "")
    if fmt not in ("mp3", "wav"):
        raise Invalid("Use MP3 or WAV audio.")
    seconds = number(result["format"].get("duration"), "Audio duration", 0.01, 120)
    return {"duration": seconds, "mime": "audio/mpeg" if fmt == "mp3" else "audio/wav"}


def image_edit(source, output, settings):
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
        crop = settings.get("crop")
        if crop is not None:
            if not isinstance(crop, list) or len(crop) != 4:
                raise Invalid("Crop requires left, top, right and bottom coordinates.")
            x1, y1, x2, y2 = [
                number(v, "Crop coordinate", 0, max(image.size)) for v in crop
            ]
            if not (x1 < x2 <= image.width and y1 < y2 <= image.height):
                raise Invalid(
                    "Crop must be inside the original image with a positive area."
                )
            image = image.crop(tuple(map(int, (x1, y1, x2, y2))))
        angle = number(settings.get("rotate", 0), "Rotation", 0, 270)
        if angle not in (0, 90, 180, 270):
            raise Invalid("Rotation must be 0, 90, 180 or 270 degrees.")
        image = image.rotate(-angle, expand=True)
        if size := settings.get("size"):
            if not isinstance(size, list) or len(size) != 2:
                raise Invalid("Resize requires width and height.")
            width, height = [int(number(v, "Output dimension", 1, 10000)) for v in size]
            if width * height > 20_000_000:
                raise Invalid("Output must be at most 20 megapixels.")
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        effect = settings.get("filter", "none")
        if effect == "greyscale":
            image = ImageOps.grayscale(image).convert("RGB")
        elif effect not in ("none", "warm", "cool"):
            raise Invalid("Choose a supported filter.")
        elif effect in ("warm", "cool"):
            r, g, b = image.split()
            r = ImageEnhance.Brightness(r).enhance(1.08 if effect == "warm" else 0.95)
            b = ImageEnhance.Brightness(b).enhance(0.95 if effect == "warm" else 1.08)
            image = Image.merge("RGB", (r, g, b))
        for field in ("brightness", "contrast"):
            value = number(settings.get(field, 1), field.title(), 0.2, 2)
            enhancer = (
                ImageEnhance.Brightness
                if field == "brightness"
                else ImageEnhance.Contrast
            )
            image = enhancer(image).enhance(value)
        image.save(output, "JPEG", quality=90, exif=b"")
        return {"width": image.width, "height": image.height, "mime": "image/jpeg"}


def audio_edit(source, output, settings, metadata):
    start = number(settings.get("start", 0), "Trim start", 0, metadata["duration"])
    end = number(
        settings.get("end", metadata["duration"]), "Trim end", 0, metadata["duration"]
    )
    volume = number(settings.get("volume", 1), "Volume", 0, 1)
    if start >= end:
        raise Invalid("Trim end must be later than trim start.")
    run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-threads",
            "1",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(source),
            "-vn",
            "-af",
            f"atrim=start={start}:end={end},asetpts=PTS-STARTPTS,volume={volume}",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output),
        ]
    )
    return {"duration": end - start, "mime": "audio/mpeg"}


def mix_audio(paths, output, length):
    args = ["ffmpeg", "-v", "error", "-nostdin", "-y", "-threads", "1"]
    for path in paths:
        args += ["-protocol_whitelist", "file,pipe", "-i", str(path)]
    filters = [
        f"[{i}:a]apad,atrim=duration={length},asetpts=PTS-STARTPTS[a{i}]"
        for i in range(len(paths))
    ]
    filters += [
        "".join(f"[a{i}]" for i in range(len(paths)))
        + f"amix=inputs={len(paths)}:normalize=1:dropout_transition=0[out]"
    ]
    run(
        args
        + [
            "-filter_complex_threads",
            "1",
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-t",
            str(length),
            "-ar",
            "44100",
            "-ac",
            "2",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output),
        ]
    )
