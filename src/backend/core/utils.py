"""Root utils for the core application."""

import ipaddress
import json
import socket
from urllib.parse import urlparse

from configurations import values


class JSONValue(values.Value):
    """
    A custom value class based on django-configurations Value class that
    allows to load a JSON string and use it as a value.
    """

    def to_python(self, value):
        """
        Return the python representation of the JSON string.
        """
        return json.loads(value)


def validate_url_safety(url: str) -> tuple[bool, str]:
    """
    Validate that a URL is safe to fetch (SSRF protection).

    This function prevents Server-Side Request Forgery (SSRF) attacks by
    validating URLs before making HTTP requests. It implements a defense-in-depth
    approach:

    1. Only allows http/https schemes
    2. Blocks all IP addresses (legitimate emails use domain names)
    3. Resolves hostnames and blocks if they resolve to private/internal IPs
       (prevents DNS rebinding attacks where attacker-controlled DNS returns
       127.0.0.1 or internal IPs)

    Blocked addresses include:
    - Any direct IP address (e.g., http://192.168.1.1/)
    - Private IP ranges (RFC1918: 10.x.x.x, 172.16-31.x.x, 192.168.x.x)
    - Loopback addresses (127.x.x.x, ::1)
    - Link-local addresses (169.254.x.x, fe80::/10)
    - Multicast and reserved addresses
    - Cloud provider metadata endpoints (169.254.169.254, fd00:ec2::254)

    Args:
        url: The URL to validate

    Returns:
        Tuple of (is_safe, error_message)
        - is_safe: True if URL is safe to fetch, False otherwise
        - error_message: Empty string if safe, error description if not

    Example:
        >>> is_safe, error = validate_url_safety("https://example.com/image.png")
        >>> if not is_safe:
        ...     return Response({"error": error}, status=403)
    """
    try:
        parsed = urlparse(url)

        # Only allow http and https schemes
        if parsed.scheme not in {"http", "https"}:
            return False, "Invalid URL scheme (only http/https allowed)"

        # Require a hostname
        if not parsed.hostname:
            return False, "Invalid URL (missing hostname)"

        # Block all IP addresses (legitimate emails use domain names)
        # This catches both IPv4 and IPv6 addresses
        try:
            ipaddress.ip_address(parsed.hostname)
            # If we get here, hostname is an IP address - block it
            return False, "IP addresses are not allowed (domain name required)"
        except ValueError:
            # Not an IP address, continue validation
            pass

        # Resolve hostname to IP addresses (prevents DNS rebinding attacks)
        # Even if the hostname is a domain now, we need to check what IPs
        # it resolves to, because attacker could control DNS
        try:
            addr_info = socket.getaddrinfo(
                parsed.hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
            )
        except socket.gaierror:
            return False, "Unable to resolve hostname"

        # Check all resolved IP addresses
        for family, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip_addr = ipaddress.ip_address(ip_str)

                # Reject private IP ranges (10.x.x.x, 192.168.x.x, 172.16-31.x.x)
                if ip_addr.is_private:
                    return False, "Domain resolves to private IP address"

                # Reject loopback (127.x.x.x, ::1)
                if ip_addr.is_loopback:
                    return False, "Domain resolves to loopback address"

                # Reject link-local (169.254.x.x, fe80::/10)
                if ip_addr.is_link_local:
                    return False, "Domain resolves to link-local address"

                # Reject multicast
                if ip_addr.is_multicast:
                    return False, "Domain resolves to multicast address"

                # Reject reserved addresses
                if ip_addr.is_reserved:
                    return False, "Domain resolves to reserved address"

                # Reject known cloud metadata IPs
                if ip_str in ("169.254.169.254", "fd00:ec2::254"):
                    return False, "Domain resolves to cloud metadata endpoint"

            except ValueError:
                return False, "Invalid IP address in DNS response"

        return True, ""

    except Exception:
        return False, "Invalid URL"
