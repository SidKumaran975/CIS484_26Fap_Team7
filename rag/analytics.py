import json
import platform
import resource
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_ACTIVE_RUN: ContextVar["RunRecorder | None"] = ContextVar(
    "active_analytics_run", default=None
)


def _max_rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux reports KiB.
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return value / divisor


class GpuPowerSampler:
    def __init__(self, interval_seconds: float = 1.0):
        self.interval_seconds = interval_seconds
        self.available = shutil.which("nvidia-smi") is not None
        self.samples: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=power.draw",
                    "--format=csv,noheader,nounits",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            watts = sum(
                float(line.strip())
                for line in result.stdout.splitlines()
                if line.strip() and line.strip().lower() != "n/a"
            )
            if watts > 0:
                self.samples.append(watts)
        except (OSError, ValueError, subprocess.SubprocessError):
            return

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        if not self.available:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop.set()
        self._thread.join(timeout=3)

    @property
    def average_watts(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0


class AnalyticsStore:
    def __init__(self, path: Path, base_watts: float):
        self.path = path
        self.base_watts = max(0.0, base_watts)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.lock = threading.Lock()
        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS analytics_runs (
                    id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    session_id TEXT,
                    question_id TEXT,
                    started_at TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    cpu_time_ms REAL NOT NULL,
                    process_max_rss_mb REAL NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    base_energy_wh_est REAL NOT NULL,
                    gpu_energy_wh_est REAL NOT NULL,
                    total_energy_wh_est REAL NOT NULL,
                    gpu_average_watts REAL NOT NULL,
                    gpu_samples INTEGER NOT NULL,
                    energy_method TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error_type TEXT,
                    stages_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS analytics_model_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    duration_ms REAL,
                    load_duration_ms REAL,
                    prompt_eval_duration_ms REAL,
                    eval_duration_ms REAL,
                    item_count INTEGER,
                    FOREIGN KEY(run_id) REFERENCES analytics_runs(id)
                );

                CREATE INDEX IF NOT EXISTS analytics_runs_started_at
                    ON analytics_runs(started_at DESC);
                CREATE INDEX IF NOT EXISTS analytics_model_calls_run_id
                    ON analytics_model_calls(run_id);
                """
            )

    def close(self) -> None:
        self.connection.close()

    def run(
        self,
        run_type: str,
        session_id: str | None = None,
        question_id: str | None = None,
    ) -> "RunRecorder":
        return RunRecorder(self, run_type, session_id, question_id)

    def save(self, recorder: "RunRecorder") -> None:
        with self.lock, self.connection:
            self.connection.execute(
                """
                INSERT INTO analytics_runs VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                recorder.row,
            )
            self.connection.executemany(
                """
                INSERT INTO analytics_model_calls (
                    run_id, operation, model, input_tokens, output_tokens,
                    duration_ms, load_duration_ms, prompt_eval_duration_ms,
                    eval_duration_ms, item_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        recorder.id,
                        call["operation"],
                        call["model"],
                        call["input_tokens"],
                        call["output_tokens"],
                        call.get("duration_ms"),
                        call.get("load_duration_ms"),
                        call.get("prompt_eval_duration_ms"),
                        call.get("eval_duration_ms"),
                        call.get("item_count"),
                    )
                    for call in recorder.model_calls
                ],
            )

    def summary(self) -> dict[str, Any]:
        with self.lock:
            totals = self.connection.execute(
                """
                SELECT
                    COUNT(*) AS run_count,
                    COALESCE(SUM(success), 0) AS successful_runs,
                    COALESCE(AVG(duration_ms), 0) AS average_duration_ms,
                    COALESCE(SUM(input_tokens), 0) AS input_tokens,
                    COALESCE(SUM(output_tokens), 0) AS output_tokens,
                    COALESCE(SUM(total_energy_wh_est), 0) AS energy_wh_est
                FROM analytics_runs
                """
            ).fetchone()
            by_type = self.connection.execute(
                """
                SELECT run_type, COUNT(*) AS runs,
                       AVG(duration_ms) AS average_duration_ms,
                       SUM(input_tokens) AS input_tokens,
                       SUM(output_tokens) AS output_tokens,
                       SUM(total_energy_wh_est) AS energy_wh_est
                FROM analytics_runs
                GROUP BY run_type
                ORDER BY run_type
                """
            ).fetchall()
        result = dict(totals)
        result["success_rate"] = (
            result["successful_runs"] / result["run_count"]
            if result["run_count"]
            else 0.0
        )
        result["by_type"] = [dict(row) for row in by_type]
        result["electricity_note"] = (
            "Estimated base-system energy plus sampled NVIDIA GPU power when "
            "nvidia-smi is available. This is operational telemetry, not a "
            "utility-grade measurement."
        )
        return result

    def recent_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT * FROM analytics_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            run_ids = [row["id"] for row in rows]
            calls_by_run: dict[str, list[dict[str, Any]]] = {
                run_id: [] for run_id in run_ids
            }
            if run_ids:
                placeholders = ",".join("?" for _ in run_ids)
                calls = self.connection.execute(
                    f"""
                    SELECT run_id, operation, model, input_tokens, output_tokens,
                           duration_ms, load_duration_ms,
                           prompt_eval_duration_ms, eval_duration_ms, item_count
                    FROM analytics_model_calls
                    WHERE run_id IN ({placeholders})
                    ORDER BY id
                    """,
                    run_ids,
                ).fetchall()
                for call in calls:
                    call_data = dict(call)
                    calls_by_run[call_data.pop("run_id")].append(call_data)
        results = []
        for row in rows:
            item = dict(row)
            item["success"] = bool(item["success"])
            item["stages"] = json.loads(item.pop("stages_json"))
            item["metrics"] = json.loads(item.pop("metrics_json"))
            item["model_calls"] = calls_by_run[item["id"]]
            results.append(item)
        return results


class RunRecorder:
    def __init__(
        self,
        store: AnalyticsStore,
        run_type: str,
        session_id: str | None,
        question_id: str | None,
    ):
        self.store = store
        self.id = str(uuid.uuid4())
        self.run_type = run_type
        self.session_id = session_id
        self.question_id = question_id
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.stages: list[dict[str, Any]] = []
        self.model_calls: list[dict[str, Any]] = []
        self.metrics: dict[str, Any] = {}
        self._start = 0.0
        self._cpu_start = 0.0
        self._token = None
        self._sampler = GpuPowerSampler()
        self.row: tuple[Any, ...] = ()

    def __enter__(self) -> "RunRecorder":
        self._start = time.perf_counter()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        self._cpu_start = usage.ru_utime + usage.ru_stime
        self._token = _ACTIVE_RUN.set(self)
        self._sampler.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self._sampler.stop()
        duration_seconds = time.perf_counter() - self._start
        usage = resource.getrusage(resource.RUSAGE_SELF)
        cpu_seconds = usage.ru_utime + usage.ru_stime - self._cpu_start
        gpu_watts = self._sampler.average_watts
        base_energy = self.store.base_watts * duration_seconds / 3600
        gpu_energy = gpu_watts * duration_seconds / 3600
        input_tokens = sum(call["input_tokens"] for call in self.model_calls)
        output_tokens = sum(call["output_tokens"] for call in self.model_calls)
        energy_method = (
            "estimated_base_plus_sampled_nvidia_gpu"
            if self._sampler.samples
            else "estimated_base_only"
        )
        self.row = (
            self.id,
            self.run_type,
            self.session_id,
            self.question_id,
            self.started_at,
            duration_seconds * 1000,
            cpu_seconds * 1000,
            _max_rss_mb(),
            input_tokens,
            output_tokens,
            base_energy,
            gpu_energy,
            base_energy + gpu_energy,
            gpu_watts,
            len(self._sampler.samples),
            energy_method,
            int(exc_type is None),
            exc_type.__name__ if exc_type else None,
            json.dumps(self.stages),
            json.dumps(self.metrics),
        )
        try:
            self.store.save(self)
        finally:
            if self._token is not None:
                _ACTIVE_RUN.reset(self._token)
        return False

    def set_context(
        self,
        session_id: str | None = None,
        question_id: str | None = None,
    ) -> None:
        if session_id is not None:
            self.session_id = session_id
        if question_id is not None:
            self.question_id = question_id

    def add_metric(self, name: str, value: Any) -> None:
        self.metrics[name] = value

    @contextmanager
    def stage(self, name: str):
        started = time.perf_counter()
        success = True
        try:
            yield
        except Exception:
            success = False
            raise
        finally:
            self.stages.append(
                {
                    "name": name,
                    "duration_ms": (time.perf_counter() - started) * 1000,
                    "success": success,
                }
            )

    def record_model_call(
        self,
        operation: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: float | None = None,
        load_duration_ms: float | None = None,
        prompt_eval_duration_ms: float | None = None,
        eval_duration_ms: float | None = None,
        item_count: int | None = None,
    ) -> None:
        self.model_calls.append(
            {
                "operation": operation,
                "model": model,
                "input_tokens": int(input_tokens or 0),
                "output_tokens": int(output_tokens or 0),
                "duration_ms": duration_ms,
                "load_duration_ms": load_duration_ms,
                "prompt_eval_duration_ms": prompt_eval_duration_ms,
                "eval_duration_ms": eval_duration_ms,
                "item_count": item_count,
            }
        )


def current_run() -> RunRecorder | None:
    return _ACTIVE_RUN.get()


@contextmanager
def analytics_stage(name: str):
    recorder = current_run()
    if recorder is None:
        yield
    else:
        with recorder.stage(name):
            yield


def record_model_call(**kwargs) -> None:
    recorder = current_run()
    if recorder is not None:
        recorder.record_model_call(**kwargs)


def record_ollama_call(
    response: Any,
    operation: str,
    model: str,
    item_count: int | None = None,
) -> None:
    def value(name: str, default: Any = 0) -> Any:
        attribute = getattr(response, name, None)
        if attribute is not None:
            return attribute
        if isinstance(response, dict):
            return response.get(name, default)
        return default

    def milliseconds(name: str) -> float | None:
        nanoseconds = value(name, None)
        return float(nanoseconds) / 1_000_000 if nanoseconds is not None else None

    record_model_call(
        operation=operation,
        model=model,
        input_tokens=value("prompt_eval_count", 0),
        output_tokens=value("eval_count", 0),
        duration_ms=milliseconds("total_duration"),
        load_duration_ms=milliseconds("load_duration"),
        prompt_eval_duration_ms=milliseconds("prompt_eval_duration"),
        eval_duration_ms=milliseconds("eval_duration"),
        item_count=item_count,
    )
