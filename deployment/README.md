# Ubuntu server deployment

These instructions target the Hartman 2011 system running Ubuntu Server 22.04
LTS with an NVIDIA RTX PRO 2000, 32 GB RAM, and a 1 TB SSD.

## 1. Clone the server branch

Create a service account and clone this branch into the path used by the
included service definition:

```bash
sudo useradd --create-home --shell /bin/bash capstone
sudo git clone --branch codex/ubuntu-server-deployment \
  https://github.com/SidKumaran975/CIS484_26Fap_Team7.git /opt/capstone
sudo chown -R capstone:capstone /opt/capstone
```

Install the base system packages, then install Python dependencies as the
service account so the environments have the correct ownership:

```bash
sudo /opt/capstone/deployment/install-system-packages.sh
sudo -u capstone /opt/capstone/deployment/install.sh
```

Install the appropriate Ubuntu NVIDIA server driver, reboot if required, and
confirm that `nvidia-smi` lists the GPU. Faster Whisper GPU execution also
requires the CUDA 12 and cuDNN 9 runtime libraries. The installer deliberately
does not replace GPU software managed by university IT.

## 2. Install Ollama and local model

Install Ollama using its supported Linux installation procedure, enable its
service, and download the configured model:

```bash
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
ollama pull llama3
sudo systemctl enable --now ollama
```

`llama3` generates faculty-reviewed exam questions. `qwen2.5:7b` performs the local rubric evaluation and follow-up generation.
`nomic-embed-text` creates the local course-document embeddings. After packages
and models have been downloaded once, assessment execution does not require a
cloud API or internet connection.

## 3. Copy files that cannot be stored in Git

Copy these files from the development machine to the exact locations below:

```text
/opt/capstone/Wav2Lip/checkpoints/wav2lip.pth
/opt/capstone/Wav2Lip/face_detection/detection/sfd/s3fd.pth
/opt/capstone/text-to-speech-model/Sid.wav
```

The voice recording may be sensitive. Transfer it over SSH/SCP and restrict
its permissions:

```bash
sudo chown capstone:capstone /opt/capstone/text-to-speech-model/Sid.wav
sudo chmod 600 /opt/capstone/text-to-speech-model/Sid.wav
```

## 4. Configure the service

```bash
sudo install -d -o capstone -g capstone /etc/capstone
sudo install -d -m 750 -o capstone -g capstone /var/lib/capstone/recordings
sudo install -d -m 750 -o capstone -g capstone /var/lib/capstone/faculty-courses
sudo install -d -m 750 -o capstone -g capstone /var/lib/capstone/faculty-indexes
sudo install -d -m 750 -o capstone -g capstone /var/lib/capstone/exams
sudo install -d -m 750 -o capstone -g capstone /var/lib/capstone/media
sudo chown -R capstone:capstone /var/lib/capstone
sudo cp /opt/capstone/deployment/capstone.env.example \
  /etc/capstone/capstone.env
sudo chown root:capstone /etc/capstone/capstone.env
sudo chmod 640 /etc/capstone/capstone.env
sudo cp /opt/capstone/deployment/capstone.service \
  /etc/systemd/system/capstone.service
sudo systemctl daemon-reload
```

Review `/etc/capstone/capstone.env`, then validate the installation:

```bash
sudo -u capstone /opt/capstone/deployment/verify.sh
```

Start the application and view its logs:

```bash
sudo systemctl enable --now capstone
sudo journalctl -u capstone -f
```

The first start can take several minutes because XTTS and Faster Whisper may
download their model data.

Create the first faculty account, then open the faculty portal on port 8001:

```bash
sudo -u capstone env DB_PATH=/var/lib/capstone/exam_builder.db \
  /opt/capstone/.venv-stt/bin/python \
  /opt/capstone/faculty-portal/manage_users.py add faculty \
  --role faculty --name "Faculty Member"
```

Faculty create courses, upload files or a folder, review generated questions,
and publish an exam. Each upload batch rebuilds that course's separate Qdrant
index with `nomic-embed-text`. Students sign in through the same portal and are
redirected to the assessment service on port 8000.

The faculty Analytics screen displays local performance analytics for indexing,
question generation, session starts, and assessment turns. It includes stage latency, CPU time, peak
process memory, Ollama input/output token counts, model timing, success rate,
and estimated watt-hours. On the NVIDIA server, GPU power is sampled with
`nvidia-smi`. `ANALYTICS_BASE_WATTS` represents estimated non-GPU system draw;
calibrate it against a wall power meter if energy accuracy is important. These
numbers are operational estimates, not utility-grade measurements.

Faculty folders support `.pdf`, `.pptx`, `.docx`, `.txt`, and `.md`. Scanned
PDFs must be OCR-processed first. A published question's private `key_points`
become the evaluator's rubric criteria; uploaded material supplies retrieved
course evidence.

## 5. Configure Nginx and HTTPS

Replace `SERVER_NAME` in `deployment/nginx-capstone.conf` with the DNS name
assigned by university IT. Then install and enable it:

```bash
sudo cp /opt/capstone/deployment/nginx-capstone.conf \
  /etc/nginx/sites-available/capstone
sudo ln -s /etc/nginx/sites-available/capstone \
  /etc/nginx/sites-enabled/capstone
sudo nginx -t
sudo systemctl reload nginx
```

Remote browser microphone access requires HTTPS. Ask university IT to provide
the hostname and TLS certificate, or use Certbot if that is permitted. Do not
expose Uvicorn port 8000 directly; only Nginx should be accessible to clients.

After HTTPS is configured, verify:

```bash
curl https://SERVER_NAME/health
```

The expected response is `{"status":"ok"}`.

## Updating the server

```bash
cd /opt/capstone
sudo -u capstone git pull --ff-only
sudo systemctl restart capstone
```

Do not run `git clean` on the server because model weights and the private
voice sample are intentionally ignored by Git.
