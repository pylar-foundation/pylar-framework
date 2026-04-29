"""Typed configuration for the mail layer."""

from __future__ import annotations

from typing import Literal

from pylar.config.schema import BaseConfig


class MailConfig(BaseConfig):
    """Driver and credentials for the bound :class:`Transport`.

    The ``driver`` field selects which transport the
    :class:`MailServiceProvider` constructs. The remaining fields are
    only consumed when the driver actually needs them — SMTP reads
    host / port / credentials, the in-process drivers ignore them.
    """

    driver: Literal["log", "memory", "smtp"] = "log"
    default_from: str = ""

    host: str = ""
    port: int = 25
    username: str = ""
    password: str = ""
    use_tls: bool = False
    use_ssl: bool = False
    timeout: float = 30.0
