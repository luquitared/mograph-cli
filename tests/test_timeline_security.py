"""Tests for timeline/security.py — SSRF prevention and path traversal."""

import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from timeline.security import SecurityError, validate_path, validate_url


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------

class TestValidateUrl:
    def test_http_allowed(self):
        """http:// URLs should pass (assuming public IP)."""
        with patch("timeline.security.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (None, None, None, None, ("93.184.216.34", 80))
            ]
            ips = validate_url("http://example.com/file.mp3")
            assert ips == ["93.184.216.34"]

    def test_https_allowed(self):
        """https:// URLs should pass."""
        with patch("timeline.security.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (None, None, None, None, ("93.184.216.34", 443))
            ]
            ips = validate_url("https://example.com/file.mp3")
            assert ips == ["93.184.216.34"]

    def test_returns_resolved_ips(self):
        """validate_url returns list of resolved IP addresses."""
        with patch("timeline.security.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (None, None, None, None, ("93.184.216.34", 80)),
                (None, None, None, None, ("93.184.216.35", 80)),
            ]
            ips = validate_url("http://example.com/file.mp3")
            assert ips == ["93.184.216.34", "93.184.216.35"]

    def test_literal_ip_returns_ip(self):
        """A literal public IP in the URL is returned."""
        ips = validate_url("http://93.184.216.34/file.mp3")
        assert ips == ["93.184.216.34"]

    def test_ftp_rejected(self):
        """ftp:// scheme should be rejected."""
        with pytest.raises(SecurityError, match="scheme.*not allowed"):
            validate_url("ftp://example.com/file.mp3")

    def test_file_scheme_rejected(self):
        """file:// scheme should be rejected."""
        with pytest.raises(SecurityError, match="scheme.*not allowed"):
            validate_url("file:///etc/passwd")

    def test_private_ip_10(self):
        """10.x.x.x addresses should be rejected."""
        with pytest.raises(SecurityError, match="disallowed IP"):
            validate_url("http://10.0.0.1/internal")

    def test_private_ip_172(self):
        """172.16.x.x addresses should be rejected."""
        with pytest.raises(SecurityError, match="disallowed IP"):
            validate_url("http://172.16.0.1/internal")

    def test_private_ip_192(self):
        """192.168.x.x addresses should be rejected."""
        with pytest.raises(SecurityError, match="disallowed IP"):
            validate_url("http://192.168.1.1/internal")

    def test_loopback_rejected(self):
        """127.0.0.1 should be rejected."""
        with pytest.raises(SecurityError, match="disallowed IP"):
            validate_url("http://127.0.0.1/internal")

    def test_localhost_rejected(self):
        """localhost should be rejected as a blocked host."""
        with pytest.raises(SecurityError, match="blocked host"):
            validate_url("http://localhost/internal")

    def test_metadata_google_rejected(self):
        """metadata.google.internal should be rejected."""
        with pytest.raises(SecurityError, match="blocked host"):
            validate_url("http://metadata.google.internal/computeMetadata/v1/")

    def test_link_local_169_254(self):
        """169.254.x.x (link-local) should be rejected."""
        with pytest.raises(SecurityError, match="disallowed IP"):
            validate_url("http://169.254.169.254/latest/meta-data/")

    def test_dns_resolving_to_private_ip(self):
        """A hostname that resolves to a private IP should be rejected."""
        with patch("timeline.security.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (None, None, None, None, ("10.0.0.5", 80))
            ]
            with pytest.raises(SecurityError, match="disallowed IP"):
                validate_url("http://evil.example.com/steal")

    def test_dns_resolving_to_public_ip_passes(self):
        """A hostname resolving to a public IP should pass."""
        with patch("timeline.security.socket.getaddrinfo") as mock_dns:
            mock_dns.return_value = [
                (None, None, None, None, ("93.184.216.34", 80))
            ]
            ips = validate_url("http://example.com/public")
            assert ips == ["93.184.216.34"]

    def test_dns_failure_raises_security_error(self):
        """DNS resolution failure should raise SecurityError, not pass silently."""
        with patch("timeline.security.socket.getaddrinfo") as mock_dns:
            mock_dns.side_effect = socket.gaierror("Name or service not known")
            with pytest.raises(SecurityError, match="DNS resolution failed"):
                validate_url("http://nonexistent.invalid/path")

    def test_url_with_userinfo_rejected(self):
        """URLs with user:pass@ credentials should be rejected."""
        with pytest.raises(SecurityError, match="credentials"):
            validate_url("http://user:pass@example.com/file")

    def test_url_with_username_only_rejected(self):
        """URLs with user@ should be rejected."""
        with pytest.raises(SecurityError, match="credentials"):
            validate_url("http://admin@example.com/file")

    def test_url_with_at_in_netloc_rejected(self):
        """URLs with @ for parser confusion should be rejected."""
        with pytest.raises(SecurityError, match="credentials"):
            validate_url("http://evil.com@169.254.169.254/metadata")


# ---------------------------------------------------------------------------
# validate_path
# ---------------------------------------------------------------------------

class TestValidatePath:
    def test_path_within_root(self, tmp_path):
        """A path inside the root directory should pass."""
        child = tmp_path / "subdir" / "file.txt"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        result = validate_path(child, tmp_path)
        assert result == child.resolve()

    def test_dotdot_rejected(self, tmp_path):
        """Paths with '..' should be rejected."""
        bad = tmp_path / "subdir" / ".." / ".." / "etc" / "passwd"
        with pytest.raises(SecurityError, match="\\.\\."):
            validate_path(bad, tmp_path)

    def test_absolute_outside_root(self, tmp_path):
        """An absolute path outside the root should be rejected."""
        with tempfile.TemporaryDirectory() as other_dir:
            outside = Path(other_dir) / "secret.txt"
            outside.touch()
            with pytest.raises(SecurityError, match="escapes allowed root"):
                validate_path(outside, tmp_path)

    def test_relative_staying_inside(self, tmp_path):
        """A relative path that stays inside root should pass."""
        subdir = tmp_path / "a" / "b"
        subdir.mkdir(parents=True)
        target = subdir / "file.txt"
        target.touch()
        result = validate_path(target, tmp_path)
        assert result.is_relative_to(tmp_path.resolve())
