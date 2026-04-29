"""Bundled HTTP middleware ready to drop into any route group."""

from pylar.http.middlewares.cors import CorsMiddleware
from pylar.http.middlewares.encrypt_cookies import EncryptCookiesMiddleware
from pylar.http.middlewares.logging import LogRequestMiddleware
from pylar.http.middlewares.maintenance import MaintenanceModeMiddleware
from pylar.http.middlewares.max_body import MaxBodySizeMiddleware
from pylar.http.middlewares.request_id import RequestIdMiddleware
from pylar.http.middlewares.secure_headers import SecureHeadersMiddleware
from pylar.http.middlewares.timeout import TimeoutMiddleware
from pylar.http.middlewares.tracing import TracingMiddleware
from pylar.http.middlewares.trim_strings import TrimStringsMiddleware
from pylar.http.middlewares.trust_proxies import TrustProxiesMiddleware

__all__ = [
    "CorsMiddleware",
    "EncryptCookiesMiddleware",
    "LogRequestMiddleware",
    "MaintenanceModeMiddleware",
    "MaxBodySizeMiddleware",
    "RequestIdMiddleware",
    "SecureHeadersMiddleware",
    "TimeoutMiddleware",
    "TracingMiddleware",
    "TrimStringsMiddleware",
    "TrustProxiesMiddleware",
]
