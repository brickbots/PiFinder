"""Safe downloads for runtime catalog data files.

Catalog updates are deliberately transactional: callers keep using the existing
file while bytes arrive in a sibling temporary file.  Only a complete,
validated response replaces the active file.
"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, NamedTuple, Optional

import requests


logger = logging.getLogger("CatalogDownload")

ProgressCallback = Callable[[Optional[int]], None]
Validator = Callable[[Path], None]
REQUEST_TIMEOUT = (5, 30)


# The kinds of a failed download. See DownloadResult.kind.
ERROR_HTTP = "http"
ERROR_NETWORK = "network"
ERROR_TIMEOUT = "timeout"
ERROR_DATA = "data"
ERROR_FILE = "file"

# The number of characters of an error response that a result keeps.
ERROR_BODY_CHARS = 200


class DownloadResult(NamedTuple):
    """The result of ``download_atomic``.

    A failed download has ``error`` (the exception text) and ``kind``: one of
    the ERROR_* values. An HTTP error also has ``status_code`` and the start
    of the response text in ``body``.
    """

    success: bool
    age_days: Optional[float]
    file_mtime: Optional[float]
    error: Optional[str] = None
    kind: Optional[str] = None
    status_code: Optional[int] = None
    body: str = ""


def _failure(exc: Exception) -> DownloadResult:
    """The result for the exception of a failed download."""
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        status = response.status_code if response is not None else None
        try:
            body = response.text[:ERROR_BODY_CHARS] if response is not None else ""
        except (OSError, ValueError, requests.RequestException):
            body = ""
        return DownloadResult(False, None, None, str(exc), ERROR_HTTP, status, body)
    if isinstance(exc, requests.Timeout):
        kind = ERROR_TIMEOUT
    elif isinstance(exc, requests.RequestException):
        kind = ERROR_NETWORK
    elif isinstance(exc, ValueError):
        kind = ERROR_DATA
    else:
        kind = ERROR_FILE
    return DownloadResult(False, None, None, str(exc), kind)


def _remote_timestamp(headers) -> Optional[float]:
    value = headers.get("Last-Modified")
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def check_download_needed(
    local_filename: Path | str,
    url: str,
    timeout: float = 5,
) -> tuple[bool, str]:
    """Compare a local catalog file with the server's Last-Modified value."""
    local_path = Path(local_filename)
    if not local_path.exists():
        return True, "no existing file"

    try:
        response = requests.head(url, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Could not check %s: %s", url, exc)
        return False, f"network error: {exc}"

    remote_mtime = _remote_timestamp(response.headers)
    if remote_mtime is None:
        return False, "cannot verify remote date"
    local_mtime = local_path.stat().st_mtime
    if remote_mtime > local_mtime:
        age_diff = (remote_mtime - local_mtime) / 86400.0
        return True, f"file outdated by {age_diff:.1f} days"
    return False, "file is up to date"


def download_atomic(
    url: str,
    local_filename: Path | str,
    progress_callback: Optional[ProgressCallback] = None,
    validator: Optional[Validator] = None,
    timeout=REQUEST_TIMEOUT,
) -> DownloadResult:
    """Download and validate ``url`` before atomically replacing the local file.

    ``progress_callback`` receives an integer percentage when Content-Length is
    known, otherwise ``None`` to request an indeterminate progress indicator.
    """
    local_path = Path(local_filename)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Optional[Path] = None
    try:
        response = requests.get(url, stream=True, timeout=timeout)
        response.raise_for_status()
        total_size = int(response.headers.get("content-length", 0) or 0)
        downloaded = 0
        if progress_callback:
            progress_callback(0 if total_size else None)

        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{local_path.name}.",
            suffix=".tmp",
            dir=local_path.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                temporary.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size:
                    progress_callback(min(99, int(downloaded * 100 / total_size)))
            temporary.flush()
            os.fsync(temporary.fileno())

        if downloaded == 0:
            raise ValueError("downloaded file is empty")
        if validator:
            validator(temporary_path)

        remote_mtime = _remote_timestamp(response.headers)
        if remote_mtime is not None:
            os.utime(temporary_path, (remote_mtime, remote_mtime))
        os.replace(temporary_path, local_path)
        temporary_path = None

        file_mtime = local_path.stat().st_mtime
        age_days = (time.time() - file_mtime) / 86400.0
        if progress_callback:
            progress_callback(100)
        return DownloadResult(True, age_days, file_mtime)
    except (OSError, ValueError, requests.RequestException) as exc:
        logger.error("Could not download %s: %s", url, exc)
        return _failure(exc)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
