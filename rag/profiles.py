"""Private, immutable professor photo/voice pairs shared by both services."""

import io
import os
import re
import tempfile
import wave
from hashlib import sha256
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .config import ROOT_DIR


def media_root() -> Path:
    return Path(os.environ.get("FACULTY_MEDIA_STORAGE", ROOT_DIR / "runtime" / "faculty-media")).resolve()


def profile_paths(professor_id: int, version: str) -> tuple[Path, Path]:
    if type(professor_id) is not int or professor_id < 1 or not re.fullmatch(r"[0-9a-f]{64}", version):
        raise ValueError("Invalid professor media reference")
    folder = media_root() / str(professor_id) / version
    return folder / "face.png", folder / "voice.wav"


def save_profile(professor_id: int, photo: bytes, voice: bytes) -> str:
    """Validate/normalize before writing; old versions remain for published exams."""
    try:
        with Image.open(io.BytesIO(photo)) as image:
            if image.format != "PNG" or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Upload a single PNG photo")
            if not all(256 <= n <= 4096 for n in image.size):
                raise ValueError("Photo dimensions must be between 256 and 4096 pixels")
            image.load()
            normalized = io.BytesIO()
            image.convert("RGB").save(normalized, format="PNG")
            photo = normalized.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The PNG photo could not be decoded") from exc
    try:
        with wave.open(io.BytesIO(voice), "rb") as audio:
            frames, rate = audio.getnframes(), audio.getframerate()
            if audio.getcomptype() != "NONE" or audio.getsampwidth() != 2 or audio.getnchannels() not in (1, 2):
                raise ValueError("Voice must be an uncompressed 16-bit PCM WAV (mono or stereo)")
            if not 16000 <= rate <= 48000 or not 6 <= frames / rate <= 30:
                raise ValueError("Voice must be 6–30 seconds at 16000–48000 Hz")
            if len(audio.readframes(frames)) != frames * audio.getnchannels() * 2:
                raise ValueError("The WAV recording is truncated")
    except (wave.Error, EOFError) as exc:
        raise ValueError("The WAV recording could not be decoded") from exc
    version = sha256(photo + voice).hexdigest()
    face_path, voice_path = profile_paths(professor_id, version)
    face_path.parent.mkdir(parents=True, exist_ok=True)
    # Immutable content names keep already-published exams stable.
    for path, payload in ((face_path, photo), (voice_path, voice)):
        if not path.exists():
            # Concurrent uploads may be identical; replace atomically using a unique temp.
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                temporary = Path(output.name)
                output.write(payload)
            try:
                temporary.replace(path)
            finally:
                temporary.unlink(missing_ok=True)
    return version
