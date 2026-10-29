#!/usr/bin/env bash
# Run only after accepting XTTS terms. Wav2Lip sources are linked by upstream.
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
curl -fL --retry 3 'https://drive.usercontent.google.com/download?id=15MzTPHCbD4FGDh1bzKqgdgq2GZqgsNvD&export=download&confirm=t' -o Wav2Lip/checkpoints/wav2lip.pth
curl -fL --retry 3 https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth -o Wav2Lip/face_detection/detection/sfd/s3fd.pth
echo '7ab9249147fd8d7884983567883222b7a86b6f94282354887825dfee7d608999  Wav2Lip/checkpoints/wav2lip.pth' | sha256sum -c -
echo '619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543  Wav2Lip/face_detection/detection/sfd/s3fd.pth' | sha256sum -c -
