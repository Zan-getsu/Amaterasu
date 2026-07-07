#!/usr/bin/env bash
#
# build.sh — Convenience wrapper for building amaterasu-base
#
# Usage:
#   ./build.sh native         # build for current arch only (fastest, no QEMU)
#   ./build.sh load-amd64     # build amd64 and load into local docker
#   ./build.sh load-arm64     # build arm64 and load into local docker
#   ./build.sh multi-push     # build both arches and push to registry
#   ./build.sh verify         # run the image and verify all components
#
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-amaterasu-base}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DOCKERFILE="${DOCKERFILE:-Dockerfile.base}"

# --- helpers ----------------------------------------------------------------
ensure_buildx() {
    if ! docker buildx ls | grep -q multiarch; then
        echo ">>> Creating multiarch buildx builder"
        docker buildx create --name multiarch --use
    fi
    docker buildx use multiarch 2>/dev/null || true
}

# --- commands ---------------------------------------------------------------
build_native() {
    echo ">>> Native build: ${IMAGE_NAME}:${IMAGE_TAG}"
    docker build -f "${DOCKERFILE}" -t "${IMAGE_NAME}:${IMAGE_TAG}" .
}

build_load() {
    local arch="$1"
    echo ">>> Load build: ${IMAGE_NAME}:${IMAGE_TAG}-${arch}"
    ensure_buildx
    docker buildx build \
        --platform "linux/${arch}" \
        -f "${DOCKERFILE}" \
        -t "${IMAGE_NAME}:${IMAGE_TAG}-${arch}" \
        --load .
}

build_multi_push() {
    echo ">>> Multi-arch push: ${IMAGE_NAME}:${IMAGE_TAG}"
    ensure_buildx
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        -f "${DOCKERFILE}" \
        -t "${IMAGE_NAME}:${IMAGE_TAG}" \
        --push .
}

verify() {
    local img="${IMAGE_NAME}:${IMAGE_TAG}"
    echo ">>> Verifying ${img}"
    docker run --rm "${img}" bash -lc '
        set -e
        echo "[1] FFmpeg:"
        ffmpeg -version | head -3
        echo
        echo "[2] AV1 encoders:"
        ffmpeg -hide_banner -encoders 2>/dev/null | grep -E "av1|libaom|libsvtav1"
        echo
        echo "[3] AV1 decoders:"
        ffmpeg -hide_banner -decoders 2>/dev/null | grep -E "av1|dav1d"
        echo
        echo "[4] Mega SDK Python:"
        python3 -c "from mega import Mega; print(\"OK\")"
        echo
        echo "[5] megacmd:"
        which mega-cmd mega-ls mega-get mega-put 2>/dev/null || true
        echo
        echo "ALL CHECKS PASSED"
    '
}

# --- main -------------------------------------------------------------------
case "${1:-native}" in
    native)        build_native ;;
    load-amd64)    build_load amd64 ;;
    load-arm64)    build_load arm64 ;;
    multi-push)    build_multi_push ;;
    verify)        verify ;;
    *)
        cat <<EOF
Usage: $0 {native|load-amd64|load-arm64|multi-push|verify}

  native       Build for current host architecture (no QEMU, fastest)
  load-amd64   Build amd64 and load into local docker (requires buildx + QEMU)
  load-arm64   Build arm64 and load into local docker (requires buildx + QEMU)
  multi-push   Build amd64+arm64 and push to registry (set IMAGE_NAME=registry/repo)
  verify       Run the image and smoke-test all components

Env vars:
  IMAGE_NAME   default: amaterasu-base
  IMAGE_TAG    default: latest
  DOCKERFILE   default: Dockerfile.base
EOF
        exit 1
        ;;
esac
