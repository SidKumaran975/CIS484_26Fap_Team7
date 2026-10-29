#!/usr/bin/env bash
set -euo pipefail
[[ ${COQUI_TOS_AGREED:-0} == 1 ]] || { echo 'Accept the XTTS-v2 CPML terms first, then set COQUI_TOS_AGREED=1.' >&2; exit 1; }
DEST=${TTS_HOME:-"$HOME/.local/share/tts"}/tts_models--multilingual--multi-dataset--xtts_v2
mkdir -p "$DEST"
for name in model.pth config.json vocab.json speakers_xtts.pth hash.md5; do
    curl -fL --retry 3 "https://huggingface.co/coqui/XTTS-v2/resolve/main/$name" -o "$DEST/$name.part"
    mv -- "$DEST/$name.part" "$DEST/$name"
done
printf '%s' 'I have read, understood and agreed to the Terms and Conditions.' > "$DEST/tos_agreed.txt"
sha256sum "$DEST/model.pth" "$DEST/config.json" "$DEST/vocab.json" "$DEST/speakers_xtts.pth"
