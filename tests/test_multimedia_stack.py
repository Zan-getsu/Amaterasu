from pathlib import Path
from re import MULTILINE, findall

ROOT = Path(__file__).parents[1]

EXPECTED_STACK = {
    "FFMPEG_VERSION": "n8.0",
    "SVT_AV1_VERSION": "v2.3.0",
    "AOM_VERSION": "v3.11.0",
    "DAV1D_VERSION": "1.5.0",
}


def test_multimedia_stack_remains_on_verified_compatibility_versions():
    dockerfile = (ROOT / "Dockerfile.base").read_text(encoding="utf-8")
    pins = dict(
        findall(
            r"^ARG (FFMPEG_VERSION|SVT_AV1_VERSION|AOM_VERSION|DAV1D_VERSION)=(\S+)$",
            dockerfile,
            MULTILINE,
        )
    )

    assert pins == EXPECTED_STACK


def test_base_image_fails_build_when_av1_stack_is_missing_or_mismatched():
    dockerfile = (ROOT / "Dockerfile.base").read_text(encoding="utf-8")

    required_checks = (
        'grep -F "ffmpeg version ${FFMPEG_VERSION#n}"',
        "pkg-config --modversion SvtAv1Enc",
        "pkg-config --modversion aom",
        "pkg-config --modversion dav1d",
        "grep -F 'libsvtav1'",
        "grep -F 'libaom-av1'",
        "grep -F 'libdav1d'",
    )
    for check in required_checks:
        assert check in dockerfile

    av1_verification = dockerfile.split("# 8. Verification", maxsplit=1)[1]
    assert "grep -E 'av1|libaom|libsvtav1' || true" not in av1_verification
    assert "grep -E 'av1|dav1d' || true" not in av1_verification


def test_ffmpeg_build_omits_non_runtime_static_libraries_and_docs():
    dockerfile = (ROOT / "Dockerfile.base").read_text(encoding="utf-8")
    ffmpeg_build = dockerfile.split("ARG FFMPEG_VERSION=", maxsplit=1)[1].split(
        "# 7. Mega SDK", maxsplit=1
    )[0]

    assert "--enable-shared" in ffmpeg_build
    assert "--disable-static" in ffmpeg_build
    assert "--disable-doc" in ffmpeg_build


def test_manual_image_verifier_checks_exact_stack_and_codec_availability():
    verifier = (ROOT / "build.sh").read_text(encoding="utf-8")

    for name in EXPECTED_STACK:
        assert f"AMATERASU_{name}" in verifier
    for codec in ("libsvtav1", "libaom-av1", "libdav1d"):
        assert f'grep -F "{codec}"' in verifier
