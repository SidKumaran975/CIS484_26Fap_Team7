import os
import subprocess
import sys
import threading
from hashlib import sha256
from pathlib import Path

from .analytics import analytics_stage
from .config import ROOT_DIR, Settings
from .profiles import profile_paths


class MediaGenerator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.lock = threading.Lock()
        self.tts_python = os.environ.get("MAIN_PYTHON", sys.executable)
        self.wav2lip_python = os.environ.get("WAV2LIP_PYTHON", sys.executable)
        self.tts_script = ROOT_DIR / "text-to-speech-model" / "run_voice.py"
        self.wav2lip_dir = ROOT_DIR / "Wav2Lip"
        self.wav2lip_script = self.wav2lip_dir / "inference.py"
        self.checkpoint = self.wav2lip_dir / "checkpoints" / "wav2lip.pth"
        self.avatar = ROOT_DIR / "BabAvatar.png"
        self.reference_audio = Path(
            os.environ.get(
                "REFERENCE_AUDIO_PATH",
                ROOT_DIR / "text-to-speech-model" / "Sid.wav",
            )
        ).expanduser().resolve()
        self.numba_cache = self.settings.media_dir.parent / "numba-cache"

    @staticmethod
    def _asset_version(path: Path) -> str:
        try:
            metadata = path.stat()
            return f"{path}:{metadata.st_size}:{metadata.st_mtime_ns}"
        except FileNotFoundError:
            return str(path)

    @staticmethod
    def _verify_output(path: Path, label: str) -> None:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"{label} did not produce a usable file: {path}")

    def _run(self, command: list[str], cwd: Path, label: str) -> None:
        environment = os.environ.copy()
        environment.setdefault("NUMBA_CACHE_DIR", str(self.numba_cache))
        environment.setdefault("MPLCONFIGDIR", str(self.numba_cache / "matplotlib"))
        try:
            subprocess.run(
                command,
                cwd=cwd,
                check=True,
                env=environment,
                timeout=self.settings.media_generation_timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"{label} exceeded {self.settings.media_generation_timeout} seconds"
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"{label} failed with exit code {exc.returncode}") from exc

    def generate(self, text: str, examiner: dict | None = None) -> str | None:
        mode = self.settings.media_mode
        if mode == "none":
            return None
        if mode not in {"audio", "avatar"}:
            raise ValueError("MEDIA_MODE must be none, audio, or avatar")
        avatar, reference_audio = self.avatar, self.reference_audio
        if examiner is not None:
            avatar, reference_audio = profile_paths(examiner["professor_id"], examiner["media_version"])
            if not reference_audio.is_file() or (mode == "avatar" and not avatar.is_file()):
                raise ValueError("This exam's professor media is missing. Restore its media files before continuing.")
        cache_parts = [text, mode, self._asset_version(reference_audio)]
        if mode == "avatar":
            cache_parts.extend(
                [
                    self._asset_version(avatar),
                    self._asset_version(self.checkpoint),
                    f"resize:{self.settings.wav2lip_resize_factor}",
                ]
            )
        media_id = sha256("\n".join(cache_parts).encode("utf-8")).hexdigest()[:24]
        audio_path = self.settings.media_dir / f"{media_id}.wav"
        video_path = self.settings.media_dir / f"{media_id}.mp4"
        final_path = video_path if mode == "avatar" else audio_path
        if final_path.is_file() and final_path.stat().st_size:
            return f"/api/media/{final_path.name}"

        with self.lock:
            if final_path.is_file() and final_path.stat().st_size:
                return f"/api/media/{final_path.name}"
            self.settings.media_dir.mkdir(parents=True, exist_ok=True)
            self.numba_cache.mkdir(parents=True, exist_ok=True)
            audio_path.unlink(missing_ok=True)
            with analytics_stage("text_to_speech"):
                self._run(
                    [
                        self.tts_python,
                        str(self.tts_script),
                        "--text",
                        text,
                        "--output",
                        str(audio_path),
                        "--reference-audio",
                        str(reference_audio),
                    ],
                    self.tts_script.parent,
                    "XTTS speech generation",
                )
            self._verify_output(audio_path, "XTTS speech generation")
            if mode == "avatar":
                video_path.unlink(missing_ok=True)
                with analytics_stage("wav2lip"):
                    self._run(
                        [
                            self.wav2lip_python,
                            str(self.wav2lip_script),
                            "--checkpoint_path",
                            str(self.checkpoint),
                            "--face",
                            str(avatar),
                            "--audio",
                            str(audio_path),
                            "--outfile",
                            str(video_path),
                            "--resize_factor",
                            str(self.settings.wav2lip_resize_factor),
                        ],
                        self.wav2lip_dir,
                        "Wav2Lip avatar generation",
                    )
                self._verify_output(video_path, "Wav2Lip avatar generation")
            return f"/api/media/{final_path.name}"
