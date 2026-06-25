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

FROM alpine:3.20

RUN set -eux; \
    apk add --no-cache bash ca-certificates curl grep; \
    arch="$(apk --print-arch)"; \
    case "$arch" in \
        x86_64) cf_arch="amd64" ;; \
        aarch64) cf_arch="arm64" ;; \
        *) echo "Unsupported cloudflared arch: $arch" && exit 1 ;; \
    esac; \
    curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors \
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${cf_arch}" \
        -o /usr/local/bin/cloudflared; \
    chmod +x /usr/local/bin/cloudflared

WORKDIR /app

# Copy the tunnel startup script that writes the URL to /data/tunnel_url.txt
COPY tunnel.sh /app/tunnel.sh
RUN chmod +x /app/tunnel.sh

# /data is the shared volume — tunnel_monitor.py in the amaterasu
# container reads /data/tunnel_url.txt from here.
VOLUME ["/data"]

ENTRYPOINT ["/app/tunnel.sh"]
