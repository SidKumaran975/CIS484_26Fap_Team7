#!/usr/bin/env bash
# Run on a machine WITH internet to (re)download every wheel the air-gapped server needs.
# Only needed if the server's Python version or CPU differs from what's already bundled.
# Usage:  bash build_bundle.sh                 # x86_64, Python 3.10 3.11 3.12
#         PY_VERSIONS="3.13" ARCH=aarch64 bash build_bundle.sh
set -euo pipefail
cd "$(dirname "$0")"
PY_VERSIONS=${PY_VERSIONS:-"3.10 3.11 3.12"}
ARCH=${ARCH:-x86_64}

rm -rf wheels && mkdir wheels
pip download pip -d wheels --only-binary=:all: --quiet
for v in $PY_VERSIONS; do
  echo "Downloading wheels for Python $v / $ARCH"
  pip download -r requirements.txt -d wheels --only-binary=:all: --quiet \
    --python-version "$v" --implementation cp \
    --platform "manylinux2014_$ARCH" --platform "manylinux_2_17_$ARCH" --platform "manylinux_2_28_$ARCH"
done
# pip skips some backports that only older Pythons need; fetch them explicitly.
pip download exceptiongroup tomli -d wheels --only-binary=:all: --quiet --python-version 3.10 --implementation cp
echo "$(ls wheels | wc -l) wheels in ./wheels. Copy the whole folder to the server."
