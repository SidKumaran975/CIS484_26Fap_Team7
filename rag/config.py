import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser().resolve()


@dataclass(frozen=True)
class Settings:
    course_content_dir: Path = field(
        default_factory=lambda: _env_path(
            "COURSE_CONTENT_DIR", ROOT_DIR / "course-materials"
        )
    )
    vector_db_path: Path = field(
        default_factory=lambda: _env_path(
            "RAG_DB_PATH", ROOT_DIR / "runtime" / "qdrant"
        )
    )
    session_db_path: Path = field(
        default_factory=lambda: _env_path(
            "SESSION_DB_PATH", ROOT_DIR / "runtime" / "sessions.sqlite3"
        )
    )
    analytics_db_path: Path = field(
        default_factory=lambda: _env_path(
            "ANALYTICS_DB_PATH", ROOT_DIR / "runtime" / "analytics.sqlite3"
        )
    )
    media_dir: Path = field(
        default_factory=lambda: _env_path("MEDIA_DIR", ROOT_DIR / "runtime" / "media")
    )
    embed_model: str = os.environ.get("RAG_EMBED_MODEL", "nomic-embed-text")
    evaluation_model: str = os.environ.get("EVALUATION_MODEL", "qwen2.5:7b")
    top_k: int = int(os.environ.get("RAG_TOP_K", "6"))
    max_follow_ups: int = int(os.environ.get("MAX_FOLLOW_UPS", "1"))
    max_audio_bytes: int = int(os.environ.get("MAX_AUDIO_BYTES", str(20 * 1024 * 1024)))
    retain_audio: bool = os.environ.get("RETAIN_AUDIO", "false").lower() in {
        "1",
        "true",
        "yes",
    }
    media_mode: str = os.environ.get("MEDIA_MODE", "avatar").lower()
    media_generation_timeout: int = int(
        os.environ.get("MEDIA_GENERATION_TIMEOUT", "600")
    )
    wav2lip_resize_factor: int = int(os.environ.get("WAV2LIP_RESIZE_FACTOR", "2"))
    analytics_base_watts: float = float(
        os.environ.get("ANALYTICS_BASE_WATTS", "30")
    )
    admin_token: str = os.environ.get("ADMIN_TOKEN", "")

    def prepare_runtime_dirs(self) -> None:
        self.vector_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.analytics_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
