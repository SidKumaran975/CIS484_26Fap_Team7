"""Checks for the upgraded Windows/WSL installation."""
import argparse
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]


def gpu():
    import torch
    import torchaudio
    assert torch.cuda.is_available(), "CUDA unavailable"
    x = torch.ones((128, 128), device="cuda")
    assert (x @ x)[0, 0].item() == 128
    print(f"PASS: torch {torch.__version__}, torchaudio {torchaudio.__version__}, {torch.cuda.get_device_name(0)}")


def wav2lip():
    import torch
    import numpy as np
    sys.path.insert(0, str(ROOT / "Wav2Lip"))
    import audio
    from models import Wav2Lip
    scripted = torch.jit.load(str(ROOT / "Wav2Lip/checkpoints/wav2lip.pth"), map_location="cpu")
    net = Wav2Lip().eval()
    net.load_state_dict(scripted.state_dict(), strict=True)
    assert audio.melspectrogram(np.zeros(16000, dtype=np.float32)).shape[0] == 80
    with torch.no_grad():
        result = net.to("cuda")(torch.zeros(1, 1, 80, 16, device="cuda"), torch.zeros(1, 6, 96, 96, device="cuda"))
    assert tuple(result.shape) == (1, 3, 96, 96)
    print("PASS: checkpoint compatibility, mel processing and Wav2Lip GPU inference")


def running():
    import httpx
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        health = client.get("http://127.0.0.1:8000/health")
        assert health.status_code == 200 and health.json()["status"] == "ok"
        assert client.get("http://127.0.0.1:8001/login").status_code == 200
        assert client.get("http://127.0.0.1:8000/api/exams").status_code == 401
        assert client.get("http://127.0.0.1:8000/").status_code == 303
        print("PASS: both services, avatar mode and required student authentication")
        print(health.json())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("component", choices=["gpu", "wav2lip", "running", "integration"])
    args = parser.parse_args()
    if args.component == "integration":
        runpy.run_path(str(ROOT / "scripts/verify-upgrade.py"), run_name="__main__")
    else:
        globals()[args.component]()
