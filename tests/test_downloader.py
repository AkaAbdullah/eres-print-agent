from pathlib import Path

import httpx
import pytest

from eres_print_agent.net.downloader import DownloadError, download_document

PDF_BYTES = b"%PDF-1.4\n%mock pdf content\n%%EOF"


def _client_for(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_successful_download_writes_file_and_hash(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret-123"
        return httpx.Response(200, content=PDF_BYTES, headers={"content-type": "application/pdf"})

    result = await download_document(
        url="https://app.eres.cloud/api/print-agent/documents/test-page/test",
        agent_secret="secret-123",
        dest_dir=tmp_path,
        job_id="job-1",
        allowed_host="app.eres.cloud",
        client=_client_for(handler),
    )

    assert result.file_path.read_bytes() == PDF_BYTES
    assert result.byte_count == len(PDF_BYTES)


@pytest.mark.asyncio
async def test_rejects_host_not_matching_paired_origin(tmp_path: Path):
    with pytest.raises(DownloadError) as exc_info:
        await download_document(
            url="https://evil.example.com/doc.pdf",
            agent_secret="secret",
            dest_dir=tmp_path,
            job_id="job-1",
            allowed_host="app.eres.cloud",
        )
    assert exc_info.value.error_code == "INVALID_JOB"


@pytest.mark.asyncio
async def test_rejects_plain_http_by_default(tmp_path: Path):
    with pytest.raises(DownloadError) as exc_info:
        await download_document(
            url="http://app.eres.cloud/doc.pdf",
            agent_secret="secret",
            dest_dir=tmp_path,
            job_id="job-1",
            allowed_host="app.eres.cloud",
        )
    assert exc_info.value.error_code == "INVALID_JOB"


@pytest.mark.asyncio
async def test_rejects_non_pdf_content_type(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html></html>", headers={"content-type": "text/html"})

    with pytest.raises(DownloadError) as exc_info:
        await download_document(
            url="https://app.eres.cloud/doc.pdf",
            agent_secret="secret",
            dest_dir=tmp_path,
            job_id="job-1",
            allowed_host="app.eres.cloud",
            client=_client_for(handler),
        )
    assert exc_info.value.error_code == "DOWNLOAD_FAILED"


@pytest.mark.asyncio
async def test_rejects_response_over_max_bytes(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PDF_BYTES, headers={"content-type": "application/pdf"})

    with pytest.raises(DownloadError) as exc_info:
        await download_document(
            url="https://app.eres.cloud/doc.pdf",
            agent_secret="secret",
            dest_dir=tmp_path,
            job_id="job-1",
            allowed_host="app.eres.cloud",
            max_bytes=4,
            client=_client_for(handler),
        )
    assert exc_info.value.error_code == "DOWNLOAD_FAILED"


@pytest.mark.asyncio
async def test_rejects_non_200_response(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with pytest.raises(DownloadError) as exc_info:
        await download_document(
            url="https://app.eres.cloud/doc.pdf",
            agent_secret="secret",
            dest_dir=tmp_path,
            job_id="job-1",
            allowed_host="app.eres.cloud",
            client=_client_for(handler),
        )
    assert exc_info.value.error_code == "DOWNLOAD_FAILED"
