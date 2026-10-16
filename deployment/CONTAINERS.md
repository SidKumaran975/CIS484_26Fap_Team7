# Ubuntu container test deployment

This deployment runs two containers:

- `app`: faculty portal, student assessment, Faster Whisper, XTTS, and Wav2Lip;
- `ollama`: question generation, answer evaluation, and embeddings.

Docker volumes preserve uploaded courses, SQLite databases, Qdrant indexes,
generated media, the XTTS model cache, and Ollama models across restarts.

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
text-to-speech-model/Sid.wav
Wav2Lip/checkpoints/wav2lip.pth
Wav2Lip/face_detection/detection/sfd/s3fd.pth
```

`BabAvatar.png` is tracked in Git and is included in the application image.

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

On the build machine:

```bash
docker compose build app
docker save -o capstone-app.tar capstone-app:latest
```

Copy `capstone-app.tar`, this repository's `compose.yaml`, `.env`, and the three
private model assets to the Ubuntu laptop. On the laptop:

```bash
docker load -i capstone-app.tar
docker compose up -d
```

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
