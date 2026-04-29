"""HTTP layer: typed Request/Response, Laravel-style middleware, ASGI kernel."""

from pylar.http.commands import ServeCommand, ServeInput
from pylar.http.error_pages import register_error_page
from pylar.http.exceptions import (
    Forbidden,
    HttpException,
    MethodNotAllowed,
    NotFound,
    Unauthorized,
    UnprocessableEntity,
)
from pylar.http.kernel import HttpKernel, HttpServerConfig
from pylar.http.middleware import Middleware, Pipeline, RequestHandler
from pylar.http.middlewares import (
    CorsMiddleware,
    EncryptCookiesMiddleware,
    LogRequestMiddleware,
    MaintenanceModeMiddleware,
    RequestIdMiddleware,
    SecureHeadersMiddleware,
    TrimStringsMiddleware,
    TrustProxiesMiddleware,
)
from pylar.http.provider import HttpServiceProvider
from pylar.http.request import Request
from pylar.http.response import (
    HtmlResponse,
    JsonResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    html,
    json,
    no_content,
    redirect,
    text,
)

__all__ = [
    "CorsMiddleware",
    "EncryptCookiesMiddleware",
    "Forbidden",
    "HtmlResponse",
    "HttpException",
    "HttpKernel",
    "HttpServerConfig",
    "HttpServiceProvider",
    "JsonResponse",
    "LogRequestMiddleware",
    "MaintenanceModeMiddleware",
    "MethodNotAllowed",
    "Middleware",
    "NotFound",
    "Pipeline",
    "PlainTextResponse",
    "RedirectResponse",
    "Request",
    "RequestHandler",
    "RequestIdMiddleware",
    "Response",
    "SecureHeadersMiddleware",
    "ServeCommand",
    "ServeInput",
    "TrimStringsMiddleware",
    "TrustProxiesMiddleware",
    "Unauthorized",
    "UnprocessableEntity",
    "html",
    "json",
    "no_content",
    "redirect",
    "register_error_page",
    "text",
]
