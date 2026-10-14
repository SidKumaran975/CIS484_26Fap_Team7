import os
import sys
import ollama
from TTS.api import TTS
import torchaudio
try:
    torchaudio.set_audio_backend("soundfile")
except Exception:
    pass

# ── PyTorch 2.6+ compatibility shim for Coqui TTS ──────────
# torch.load now defaults to weights_only=True, but XTTS v2
# checkpoints contain custom config objects that require
# weights_only=False.  Monkey-patch to restore the old default.
import torch
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load
# ────────────────────────────────────────────────────────────

# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------
# Direct path to your reference voice sample (same directory as this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCE_AUDIO_PATH = os.environ.get(
    "REFERENCE_AUDIO_PATH",
    os.path.join(SCRIPT_DIR, "Sid.wav"),
)

# Temporary audio file destination for playback
OUTPUT_AUDIO_PATH = "output_response.wav"

# Local Ollama model name
MODEL_NAME = os.environ.get("OLLAMA_MODEL", "llama3")


def main():
    # 1. VERIFY AUDIO SAMPLE PATH
    # Check that the voice sample exists at the exact path before proceeding
    if not os.path.exists(REFERENCE_AUDIO_PATH):
        print(f"Error: Could not find audio file at: {REFERENCE_AUDIO_PATH}")
        sys.exit(1)

    print(f"Loaded voice reference: {REFERENCE_AUDIO_PATH}")

    # 2. GENERATE TEXT VIA OLLAMA (LLAMA 3)
    print("\nQuerying Llama 3 for a sample greeting...")
    prompt = "Give a brief, one-sentence friendly greeting introducing yourself as an AI assistant."

    response = ollama.chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": "You are a concise voice assistant. Output plain text only—no asterisks, quotes, or markdown."
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    generated_text = response["message"]["content"].strip()
    print(f"Llama 3 output: \"{generated_text}\"")

    # 3. LOAD XTTS MODEL
    # Loads the XTTS v2 model into memory (will download weights on the first run)
    print("\nLoading XTTS v2 model...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using {device.upper()} for speech synthesis.")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    # 4. SYNTHESIZE SPEECH
    # Clones the vocal characteristics from Sid.wav and generates the speech file
    print("Synthesizing audio using cloned voice...")
    tts.tts_to_file(
        text=generated_text,
        speaker_wav=REFERENCE_AUDIO_PATH,
        language="en",
        file_path=OUTPUT_AUDIO_PATH
    )


if __name__ == "__main__":
    main()
