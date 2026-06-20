#!/bin/bash
# Phase 1.7 — Cloudflare Quick Tunnel startup script
# Starts cloudflared in quick-tunnel mode, captures the trycloudflare.com
# URL from the logs, and writes it to /data/tunnel_url.txt for the
# amaterasu container's tunnel_monitor.py to pick up.
#
# The URL rotates on every restart — this is a limitation of quick
# tunnels. For a persistent URL, use a named tunnel instead (set
# CLOUDFLARE_TUNNEL_TOKEN in your config).

set -e

# Target is the amaterasu container's web UI (same network via
# network_mode: "service:amaterasu" in docker-compose)
TARGET="${CLOUDFLARE_TUNNEL_TARGET:-http://localhost:8080}"
URL_FILE="${TUNNEL_URL_FILE:-/data/tunnel_url.txt}"

echo "[tunnel] Starting cloudflared quick tunnel -> ${TARGET}"
echo "[tunnel] URL will be written to ${URL_FILE}"

mkdir -p "$(dirname "${URL_FILE}")"

# Start cloudflared in quick-tunnel mode. Capture stderr+stdout, then
# grep for the trycloudflare.com URL and write it to the file.
cloudflared tunnel --url "${TARGET}" --no-autoupdate 2>&1 | while IFS= read -r line; do
    echo "${line}"
    # cloudflared logs the URL in a line like:
    #   "Your quick Tunnel has been created! Visit it at: https://xxx.trycloudflare.com"
    if echo "${line}" | grep -qoE "https://[a-z0-9-]+\.trycloudflare\.com"; then
        URL=$(echo "${line}" | grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" | head -1)
        echo "[tunnel] Detected URL: ${URL}"
        echo "${URL}" > "${URL_FILE}"
        echo "[tunnel] URL written to ${URL_FILE}"
    fi
done
