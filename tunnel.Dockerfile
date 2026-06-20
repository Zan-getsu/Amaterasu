# Phase 1.7 — Cloudflare Quick Tunnel container
# Runs cloudflared in quick-tunnel mode, pointing at the amaterasu
# container's port 8080. The trycloudflare.com URL is captured by
# tunnel.sh and written to /data/tunnel_url.txt, which
# bot/helper/ext_utils/tunnel_monitor.py watches and propagates to the
# bot + owner DM.
#
# For a persistent URL (no rotation on restart), use a named tunnel
# instead: set CLOUDFLARE_TUNNEL_TOKEN in your config and the bot's
# built-in cloudflare_tunnel.py will handle it directly — no separate
# tunnel container needed.

FROM cloudflare/cloudflared:latest

WORKDIR /app

# Copy the tunnel startup script that writes the URL to /data/tunnel_url.txt
COPY tunnel.sh /app/tunnel.sh
RUN chmod +x /app/tunnel.sh

# /data is the shared volume — tunnel_monitor.py in the amaterasu
# container reads /data/tunnel_url.txt from here.
VOLUME ["/data"]

ENTRYPOINT ["/app/tunnel.sh"]
