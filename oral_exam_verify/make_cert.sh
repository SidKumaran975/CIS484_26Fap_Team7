#!/usr/bin/env bash
# Creates a self-signed HTTPS certificate using the openssl already on Ubuntu.
# Needs no internet. Usage:  ./make_cert.sh <server-ip-or-hostname> [more names/IPs...]
# Example:                   ./make_cert.sh 192.168.1.50 examserver.local
set -euo pipefail
cd "$(dirname "$0")"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <server-ip-or-hostname> [more names/IPs...]" >&2
  exit 1
fi

san="DNS:localhost,IP:127.0.0.1"
for name in "$@"; do
  if [[ "$name" =~ ^[0-9.]+$ ]]; then san+=",IP:$name"; else san+=",DNS:$name"; fi
done

openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout key.pem -out cert.pem \
  -subj "/CN=$1" -addext "subjectAltName=$san"
chmod 600 key.pem
echo "Wrote cert.pem and key.pem (valid 365 days) for: $san"
echo "Students' browsers will show a one-time warning for a self-signed cert;"
echo "import cert.pem into the lab machines' trust store to remove it."
