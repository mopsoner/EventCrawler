import hmac
import ipaddress
import socket
from urllib.parse import urlparse


ALLOWED_SOURCE_HOSTS = frozenset({"bizouk.com", "www.bizouk.com", "kiwol.com", "www.kiwol.com"})


class UnsafeURL(ValueError):
    pass


def _is_allowed_host(hostname, allowed_hosts):
    hostname = hostname.rstrip(".").lower()
    return any(hostname == host or hostname.endswith(f".{host}") for host in allowed_hosts)


def validate_external_url(value, allowed_hosts=ALLOWED_SOURCE_HOSTS, resolve_dns=True):
    """Return a normalized HTTPS URL after host and resolved-address checks."""
    try:
        parsed = urlparse(str(value or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise UnsafeURL("URL invalide") from exc
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise UnsafeURL("seules les URL HTTPS sans identifiants sont autorisées")
    if port not in (None, 443) or not _is_allowed_host(hostname, allowed_hosts):
        raise UnsafeURL("hôte ou port non autorisé")
    if resolve_dns:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)}
        except socket.gaierror as exc:
            raise UnsafeURL("hôte impossible à résoudre") from exc
        if not addresses:
            raise UnsafeURL("hôte impossible à résoudre")
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global:
                raise UnsafeURL("adresse réseau privée ou réservée interdite")
    return parsed._replace(fragment="").geturl()


def credentials_match(provided_user, provided_password, expected_user, expected_password):
    return hmac.compare_digest(provided_user or "", expected_user or "") and hmac.compare_digest(
        provided_password or "", expected_password or ""
    )
