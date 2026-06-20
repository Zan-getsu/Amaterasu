"""Phase 2.8 — Actionable error messages.

Defines BotError class with fields: code, user_message, suggestion,
log_message. Each user_message is a complete sentence. Each suggestion
tells the user exactly what to do next.

Used to replace generic "An error occurred" messages with specific,
actionable ones.
"""

from logging import getLogger

LOGGER = getLogger(__name__)


class BotError(Exception):
    """Exception with a user-friendly message and actionable suggestion.

    Attributes:
        code: Error code string (e.g., 'DISK_FULL', 'NETWORK_TIMEOUT').
        user_message: Complete sentence describing what went wrong.
            Shown to the user in Telegram.
        suggestion: What the user should do next. Shown to the user
            in Telegram, appended to user_message.
        log_message: Technical message for the log file (includes
            debug details not shown to the user).
    """

    def __init__(self, code, user_message, suggestion="", log_message=""):
        self.code = code
        self.user_message = user_message
        self.suggestion = suggestion
        self.log_message = log_message or user_message
        super().__init__(self.user_message)

    def to_user_message(self):
        """Return the full message to send to the user (message + suggestion)."""
        if self.suggestion:
            return f"{self.user_message}\n\n💡 {self.suggestion}"
        return self.user_message

    def __str__(self):
        return self.to_user_message()


# ────────────────────────────────────────────────────────────────────
# Predefined error factories — use these instead of constructing
# BotError directly for common error types.
# ────────────────────────────────────────────────────────────────────

def disk_full(required_gb, available_gb, download_dir):
    """Not enough disk space for the download."""
    return BotError(
        code="DISK_FULL",
        user_message=(
            f"Not enough disk space. Need {required_gb:.1f} GB, "
            f"have {available_gb:.1f} GB free."
        ),
        suggestion=(
            f"Free up space in {download_dir} or ask the admin to "
            f"increase storage."
        ),
        log_message=f"Disk full: required {required_gb}GB, available {available_gb}GB at {download_dir}",
    )


def network_timeout(url, timeout_seconds):
    """Network operation timed out."""
    return BotError(
        code="NETWORK_TIMEOUT",
        user_message=f"Connection timed out after {timeout_seconds} seconds.",
        suggestion=(
            "The server may be down or slow. Try again in a few minutes, "
            "or try a different download source."
        ),
        log_message=f"Network timeout for {url} after {timeout_seconds}s",
    )


def engine_unavailable(engine_name, reason=""):
    """Download engine is not running or not responding."""
    return BotError(
        code="ENGINE_UNAVAILABLE",
        user_message=f"The {engine_name} engine is not available right now.",
        suggestion=(
            f"Try again in a few minutes. If the problem persists, "
            f"contact the bot owner.{' Details: ' + reason if reason else ''}"
        ),
        log_message=f"Engine {engine_name} unavailable: {reason}",
    )


def auth_failed(service):
    """Authentication failed for a service."""
    return BotError(
        code="AUTH_FAILED",
        user_message=f"Authentication failed for {service}.",
        suggestion=(
            "Check that your API key or credentials are correct in the "
            "bot settings. If you're the owner, verify the config."
        ),
        log_message=f"Auth failed for {service}",
    )


def file_too_large(file_size_gb, limit_gb, service):
    """File exceeds the size limit for the target service."""
    return BotError(
        code="FILE_TOO_LARGE",
        user_message=(
            f"File is {file_size_gb:.1f} GB but {service} limit is "
            f"{limit_gb:.1f} GB."
        ),
        suggestion=(
            "Split the file before uploading, or use a different upload "
            "destination with a higher limit."
        ),
        log_message=f"File too large: {file_size_gb}GB > {limit_gb}GB limit for {service}",
    )


def rate_limited(service, retry_after_seconds):
    """Rate limited by a service."""
    return BotError(
        code="RATE_LIMITED",
        user_message=f"Rate limited by {service}. Try again in {retry_after_seconds} seconds.",
        suggestion=(
            "Wait for the cooldown period before sending another request. "
            "If this happens often, ask the admin to reduce concurrency."
        ),
        log_message=f"Rate limited by {service}: retry after {retry_after_seconds}s",
    )


def download_failed(url, reason):
    """Generic download failure."""
    return BotError(
        code="DOWNLOAD_FAILED",
        user_message="The download failed and could not be retried.",
        suggestion=(
            "Check that the URL is correct and accessible. If the source "
            "requires authentication, make sure credentials are configured. "
            f"Details: {reason}"
        ),
        log_message=f"Download failed for {url}: {reason}",
    )


def upload_failed(destination, reason):
    """Generic upload failure."""
    return BotError(
        code="UPLOAD_FAILED",
        user_message=f"Upload to {destination} failed.",
        suggestion=(
            "Check that the destination is accessible and credentials are "
            f"valid. Details: {reason}"
        ),
        log_message=f"Upload failed to {destination}: {reason}",
    )
