FROM python:3.11-slim-bookworm

# The portable Compose deployment is CPU-first. Installing PyTorch from the
# default PyPI index also pulls several gigabytes of CUDA libraries on Linux,
# even when the container has no GPU access. Override this build argument only
# when building a GPU-specific image with a compatible wheel source.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    XDG_CACHE_HOME=/home/capstone/.cache \
    XDG_DATA_HOME=/home/capstone/.local/share

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY deployment/requirements-stt.txt deployment/requirements-tts.txt deployment/requirements-wav2lip.txt /tmp/requirements/
COPY faculty-portal/requirements.txt /tmp/requirements/faculty.txt

RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install --index-url "${TORCH_INDEX_URL}" torch torchaudio torchvision \
    && python -m pip install \
        -r /tmp/requirements/requirements-stt.txt \
        -r /tmp/requirements/requirements-tts.txt \
        -r /tmp/requirements/requirements-wav2lip.txt \
        -r /tmp/requirements/faculty.txt

COPY . /app

RUN useradd --create-home --uid 10001 capstone \
    && mkdir -p /data /home/capstone/.cache /home/capstone/.local/share/tts \
    && chown -R capstone:capstone /data /home/capstone /app

USER capstone

EXPOSE 8000 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)" || exit 1

CMD ["python", "pipeline.py"]
