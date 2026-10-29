import argparse
import os
import sys

from TTS.api import TTS
import torch

# Maintained coqui-tts handles checkpoint compatibility internally.

# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------
# Direct path to your reference voice sample (same directory as this script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REFERENCE_AUDIO_PATH = os.environ.get(
    "REFERENCE_AUDIO_PATH",
    os.path.join(SCRIPT_DIR, "Sid.wav"),
)


def synthesize(text: str, output_path: str, reference_audio: str = REFERENCE_AUDIO_PATH) -> None:
    # 1. VERIFY AUDIO SAMPLE PATH
    # Check that the voice sample exists at the exact path before proceeding
    if not os.path.exists(reference_audio):
        print(f"Error: Could not find audio file at: {reference_audio}")
        sys.exit(1)

    print(f"Loaded voice reference: {reference_audio}")

    # 2. LOAD XTTS MODEL
    # Loads the XTTS v2 model into memory (will download weights on the first run)
    print("\nLoading XTTS v2 model...")
    device = os.environ.get("TTS_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using {device.upper()} for speech synthesis.")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    # 3. SYNTHESIZE SPEECH
    # Clones the vocal characteristics from Sid.wav and generates the speech file
    print("Synthesizing audio using cloned voice...")
    tts.tts_to_file(
        text=text,
        speaker_wav=reference_audio,
        language="en",
        file_path=output_path,
    )


def main():
    parser = argparse.ArgumentParser(description="Synthesize assessment speech")
    parser.add_argument("--text", required=True, help="Text to speak")
    parser.add_argument("--output", required=True, help="Output WAV path")
    parser.add_argument("--reference-audio", default=REFERENCE_AUDIO_PATH, help="Professor reference WAV")
    args = parser.parse_args()
    synthesize(args.text, args.output, args.reference_audio)


if __name__ == "__main__":
    main()
