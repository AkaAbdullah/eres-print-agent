"""Fetches a print job's document — the only place this agent is allowed
to reach out over the network to something other than print-hub.

Spec section 25/29: validate URL, HTTPS, content type, file size; no
arbitrary local file access, no shell execution. `allowed_host` is pinned
at pairing time from the paired web/ app's own origin (see
core/pairing.py) — a job whose documentUrl points anywhere else is
rejected outright rather than trusted just because print-hub relayed it.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

from ..constants import DOWNLOAD_MAX_BYTES, DOWNLOAD_TIMEOUT_SECONDS

ALLOWED_CONTENT_TYPES = ("application/pdf",)


class DownloadError(Exception):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass
class DownloadResult:
    file_path: Path
    byte_count: int
    sha256: str


def _validate_url(url: str, allowed_host: Optional[str], allow_insecure_http: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise DownloadError("INVALID_JOB", f"Unsupported URL scheme: {parsed.scheme!r}")
    if parsed.scheme == "http" and not allow_insecure_http:
        raise DownloadError("INVALID_JOB", "Refusing to fetch a document over plain HTTP")
    if allowed_host and parsed.hostname != allowed_host:
        raise DownloadError(
            "INVALID_JOB",
            f"documentUrl host {parsed.hostname!r} does not match the paired ERES host {allowed_host!r}",
        )


async def download_document(
    *,
    url: str,
    agent_secret: str,
    dest_dir: Path,
    job_id: str,
    allowed_host: Optional[str],
    allow_insecure_http: bool = False,
    max_bytes: int = DOWNLOAD_MAX_BYTES,
    timeout_seconds: int = DOWNLOAD_TIMEOUT_SECONDS,
    client: Optional[httpx.AsyncClient] = None,
) -> DownloadResult:
    """`client` is injectable so tests can pass an httpx.MockTransport-backed
    client instead of making real network calls; production callers omit it
    and get a real one scoped to this single download."""
    _validate_url(url, allowed_host, allow_insecure_http)

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{job_id}.pdf"

    hasher = hashlib.sha256()
    byte_count = 0

    async def _run(active_client: httpx.AsyncClient) -> None:
        nonlocal byte_count
        async with active_client.stream(
            "GET", url, headers={"Authorization": f"Bearer {agent_secret}"}
        ) as response:
            if response.status_code != 200:
                raise DownloadError("DOWNLOAD_FAILED", f"Document fetch returned HTTP {response.status_code}")

            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise DownloadError("DOWNLOAD_FAILED", f"Unexpected content type: {content_type or '(none)'}")

            with open(dest_path, "wb") as f:
                async for chunk in response.aiter_bytes():
                    byte_count += len(chunk)
                    if byte_count > max_bytes:
                        raise DownloadError("DOWNLOAD_FAILED", f"Document exceeds max size of {max_bytes} bytes")
                    hasher.update(chunk)
                    f.write(chunk)

    try:
        if client is not None:
            await _run(client)
        else:
            async with httpx.AsyncClient(timeout=timeout_seconds) as owned_client:
                await _run(owned_client)
    except httpx.TimeoutException as error:
        raise DownloadError("TIMEOUT", f"Document download timed out: {error}") from error
    except httpx.HTTPError as error:
        raise DownloadError("DOWNLOAD_FAILED", f"Document download failed: {error}") from error

    if byte_count == 0:
        raise DownloadError("DOWNLOAD_FAILED", "Document was empty")

    return DownloadResult(file_path=dest_path, byte_count=byte_count, sha256=hasher.hexdigest())
