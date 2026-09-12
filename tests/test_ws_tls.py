"""The hub's Let's Encrypt chain terminates at ISRG Root X2. Plenty of
Windows 10 machines lack that root, and a service running as LocalSystem does
not pick up Windows' automatic root updates — so verifying against the OS
trust store failed with CERTIFICATE_VERIFY_FAILED on every reconnect and the
agent could never come online.
"""

import ssl

import certifi

from eres_print_agent.net import ws_client


def test_wss_urls_verify_against_the_certifi_bundle():
    context = ws_client._ssl_context("wss://api.eres.cloud/print-agent")

    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_plain_ws_needs_no_context():
    assert ws_client._ssl_context("ws://localhost:4100/print-agent") is None


def test_certifi_bundle_is_readable():
    # certifi.where() points at a real file that must survive PyInstaller
    # bundling; an empty or missing bundle verifies nothing.
    with open(certifi.where(), "rb") as handle:
        assert b"BEGIN CERTIFICATE" in handle.read(4096)
