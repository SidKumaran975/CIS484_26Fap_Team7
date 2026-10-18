# Ubuntu container test deployment

This deployment runs two containers:

- `app`: faculty portal, student assessment, Faster Whisper, XTTS, and Wav2Lip;
- `ollama`: question generation, answer evaluation, and embeddings.

Docker volumes preserve uploaded courses, SQLite databases, Qdrant indexes,
generated media, the XTTS model cache, and Ollama models across restarts.
Student audio is transcribed by Faster Whisper during each assessment turn. The
examiner prompts, student identity, and resulting text are stored in the
`capstone-data` volume and appear in the faculty portal's **Transcripts** view.
Raw recordings are deleted after transcription unless `RETAIN_AUDIO=true`.

## 1. Prepare the Ubuntu laptop

Install Docker Engine with the Compose plugin, then confirm:

```bash
docker --version
docker compose version
```

Clone this branch or copy the repository to the laptop. The following local
assets are intentionally not stored in GitHub and must be copied into the same
paths before starting:

```text
BabAvatar.png
text-to-speech-model/Sid.wav
Wav2Lip/checkpoints/wav2lip.pth
Wav2Lip/face_detection/detection/sfd/s3fd.pth
```

## 2. Configure and build

```bash
cp .env.container.example .env
```

Review the Coqui Public Model License. If its terms are acceptable for the
test, set `COQUI_TOS_AGREED=1` in `.env`. Then build the application image:

```bash
docker compose build app
docker compose up -d ollama
```

The base Compose file uses CPU-only PyTorch wheels and
`WHISPER_DEVICE=cpu`. The Hartman 2011 machine's 16 GB RTX PRO 2000 is a
Blackwell GPU, whose first supported CUDA toolkit is CUDA 12.8. Install a
current NVIDIA driver that supports CUDA 12.8 and the NVIDIA Container Toolkit,
configure Docker, and verify access:

```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.8.1-base-ubuntu22.04 nvidia-smi
```

Then build and start with both Compose files. The override uses the official
PyTorch 2.9.1 runtime with CUDA 12.8 and cuDNN 9, exposes the same GPU to the
app and Ollama containers, and changes Faster Whisper to CUDA/float16. XTTS,
Wav2Lip, and Ollama automatically select the GPU when it is available.

```bash
docker compose -f compose.yaml -f compose.gpu.yaml build app
docker compose -f compose.yaml -f compose.gpu.yaml up -d
docker compose -f compose.yaml -f compose.gpu.yaml exec app \
  python -c 'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))'
```

For the rest of this guide, keep using both `-f compose.yaml -f
compose.gpu.yaml` arguments for every command that manages the GPU `app`
service. The shorter commands below are the CPU form.

Pull the three required Ollama models once:

```bash
docker compose exec ollama ollama pull llama3
docker compose exec ollama ollama pull qwen2.5:7b
docker compose exec ollama ollama pull nomic-embed-text
```

Start the complete system:

```bash
docker compose up -d
docker compose ps
docker compose logs -f app
```

The first avatar question downloads the XTTS model into the persistent
`tts-models` volume and can take several minutes on a CPU-only laptop.

## 3. Create accounts

```bash
docker compose exec app python faculty-portal/manage_users.py add faculty1 --role faculty --name "Faculty User"
docker compose exec app python faculty-portal/manage_users.py add student1 --role student --name "Student User"
```

The script securely prompts for each password.

## 4. Open from another computer

Find the laptop's address:

```bash
hostname -I
```

Open these URLs, replacing `UBUNTU_IP` with that address:

```text
http://UBUNTU_IP:8001/login
http://UBUNTU_IP:8000
```

If Ubuntu's firewall is enabled:

```bash
sudo ufw allow 8000/tcp
sudo ufw allow 8001/tcp
```

Port `11434` only needs to be exposed for direct Ollama troubleshooting. It
should not be exposed outside a trusted test network.

## Moving the built image without rebuilding

Docker images are architecture-specific. Check both machines first:

```bash
docker info --format '{{.Architecture}}'
uname -m
```

An image built normally on an Apple-silicon Mac is `arm64` and will not run on
a typical `x86_64`/`amd64` Ubuntu server. For an amd64 NVIDIA server, build and
load an amd64 image on the Mac before exporting it:

On the build machine:

```bash
docker buildx build --platform linux/amd64 --load \
  -f Dockerfile.gpu -t capstone-app:latest .
docker save -o capstone-app.tar capstone-app:latest
```

Copy `capstone-app.tar`, this repository's `compose.yaml`, `compose.gpu.yaml`,
`.env`, and the four private model assets to the Ubuntu server. On the server:

```bash
docker load -i capstone-app.tar
docker compose -f compose.yaml -f compose.gpu.yaml up -d --no-build
```

Alternatively, copy the repository and private assets to the server and run
`docker compose -f compose.yaml -f compose.gpu.yaml build app` there. Building
on the server automatically uses its native architecture and is usually faster
than emulation on a Mac.

The exact Compose image name can be checked with:

```bash
docker compose images
```

## Useful troubleshooting capture

Record these outputs before changing anything during a failure:

```bash
date -Is
docker compose ps
docker compose images
docker compose logs --since=15m app
docker compose logs --since=15m ollama
docker stats --no-stream
df -h
free -h
```

Do not include `.env`, passwords, session cookies, private voice recordings, or
student recordings in a shared troubleshooting report.
