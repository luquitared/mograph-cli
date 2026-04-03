"""Security utilities for SSRF prevention and path traversal protection.

Used by the timeline validator and file_source adapter to ensure URLs and
file paths don't access internal services or escape allowed directories.
"""

import ipaddress
import socket
from pathlib import Path
from typing import List
from urllib.parse import urlparse


class SecurityError(Exception):
    """Raised when a URL or path violates security constraints."""
    pass


# Hostnames that must always be blocked regardless of resolution
_BLOCKED_HOSTS = frozenset({
    "metadata.google.internal",
    "localhost",
})


def validate_url(url: str) -> List[str]:
    """Validate a URL is safe to fetch (no SSRF) and return resolved IPs.

    Only http:// and https:// schemes are allowed.  Hostnames are resolved
    and checked against RFC 1918 private ranges, loopback, link-local, and
    cloud metadata endpoints.

    Returns:
        List of resolved IP address strings (pinned for subsequent connection).

    Raises:
        SecurityError: If the URL is disallowed.
    """
    parsed = urlparse(url)

    # Scheme check
    if parsed.scheme not in ("http", "https"):
        raise SecurityError(
            f"URL scheme '{parsed.scheme}' is not allowed. Only http and https are permitted: {url}"
        )

    # Reject URLs with userinfo (parser confusion attacks)
    if parsed.username or parsed.password or "@" in (parsed.netloc or "").split(":")[0]:
        raise SecurityError("URLs with credentials are not allowed")

    hostname = parsed.hostname or ""

    # Explicit blocked hostnames
    if hostname in _BLOCKED_HOSTS:
        raise SecurityError(
            f"URL targets a blocked host: {hostname}"
        )

    # Check if hostname is a literal IP
    try:
        addr = ipaddress.ip_address(hostname)
        _check_ip(addr, hostname)
        return [str(addr)]
    except ValueError:
        pass  # Not a literal IP — resolve via DNS

    # DNS resolution check — fail closed on errors
    resolved_ips: List[str] = []
    try:
        infos = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in infos:
            addr = ipaddress.ip_address(sockaddr[0])
            _check_ip(addr, hostname)
            resolved_ips.append(sockaddr[0])
    except socket.gaierror:
        raise SecurityError(f"DNS resolution failed for {hostname}")

    if not resolved_ips:
        raise SecurityError(f"No DNS results for {hostname}")

    return resolved_ips


def _check_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, hostname: str) -> None:
    """Raise SecurityError if the IP is private, loopback, or link-local."""
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        raise SecurityError(
            f"URL resolves to a disallowed IP address: {hostname} -> {addr}"
        )


def validate_path(path: Path, allowed_root: Path) -> Path:
    """Validate that a file path stays within the allowed root directory.

    Rejects paths containing '..' components (checked before resolution)
    and paths that resolve outside the allowed root.

    Args:
        path: The path to validate.
        allowed_root: The root directory paths must stay within.

    Returns:
        The resolved absolute path.

    Raises:
        SecurityError: If the path escapes the allowed root.
    """
    resolved = path.resolve()
    allowed = allowed_root.resolve()

    if not resolved.is_relative_to(allowed):
        raise SecurityError(
            f"Path escapes allowed root: {path} resolves to {resolved}, "
            f"which is outside {allowed}"
        )

    return resolved
