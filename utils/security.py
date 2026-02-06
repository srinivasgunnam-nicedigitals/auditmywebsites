import socket
from urllib.parse import urlparse
import ipaddress
import httpx
from typing import Optional, Tuple

def is_safe_url(url: str) -> bool:
    """
    Check if a URL is safe to fetch (prevents SSRF).
    Blocks private IPs, loopback, and reserved ranges.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        
        hostname = parsed.hostname
        if not hostname:
            return False

        # Resolve hostname to IP
        try:
            ip_address = socket.gethostbyname(hostname)
        except socket.gaierror:
            return False

        ip = ipaddress.ip_address(ip_address)

        # Block loopback, private, link-local, and multicast addresses
        if (ip.is_loopback or 
            ip.is_private or 
            ip.is_link_local or 
            ip.is_multicast or 
            ip.is_reserved or 
            ip.is_unspecified):
            return False

        # Explicitly block AWS/GCP metadata IPs
        metadata_ips = ['169.254.169.254', 'metadata.google.internal']
        if ip_address in metadata_ips:
            return False

        return True
    except Exception:
        return False

async def safe_fetch(url: str, **kwargs) -> Optional[httpx.Response]:
    """
    Safely fetch a URL with SSRF protection and timeout.
    """
    if not is_safe_url(url):
        return None
    
    # Ensure reasonable defaults for security
    kwargs.setdefault('timeout', 15.0)
    kwargs.setdefault('follow_redirects', True)
    kwargs.setdefault('verify', True) # SAFETY FIRST
    
    async with httpx.AsyncClient(**kwargs) as client:
        try:
            response = await client.get(url)
            # Re-check URL after redirects
            if not is_safe_url(str(response.url)):
                return None
            return response
        except Exception:
            return None
