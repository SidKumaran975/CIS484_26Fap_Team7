import os
import subprocess
import ollama
from TTS.api import TTS
import torchaudio
try:
    torchaudio.set_audio_backend("soundfile")
except Exception:
    pass

# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------
# Direct path to your reference voice sample
REFERENCE_AUDIO_PATH = "/Users/sid/Downloads/CIS484Capstone/Capstone/Sid.wav"

# Temporary audio file destination for playback
OUTPUT_AUDIO_PATH = "output_response.wav"

# Local Ollama model name
MODEL_NAME = "llama3"


def main():
    # 1. VERIFY AUDIO SAMPLE PATH
    # Check that the voice sample exists at the exact path before proceeding
    if not os.path.exists(REFERENCE_AUDIO_PATH):
        print(f"Error: Could not find audio file at: {REFERENCE_AUDIO_PATH}")
        return

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
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

    # 4. SYNTHESIZE SPEECH
    # Clones the vocal characteristics from Sid.wav and generates the speech file
    print("Synthesizing audio using cloned voice...")
    tts.tts_to_file(
        text=generated_text,
        speaker_wav=REFERENCE_AUDIO_PATH,
        language="en",
        file_path=OUTPUT_AUDIO_PATH
    )

    # 5. PLAY AUDIO
    # 'afplay' is macOS's built-in command-line audio player
    print(f"Playing generated audio ({OUTPUT_AUDIO_PATH})...")
    subprocess.run(["afplay", OUTPUT_AUDIO_PATH])
    print("Finished playback.")


if __name__ == "__main__":
    main()