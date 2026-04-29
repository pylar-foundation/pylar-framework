"""Service provider that wires the mail layer."""

from __future__ import annotations

from pylar.foundation.container import Container
from pylar.foundation.provider import ServiceProvider
from pylar.mail.config import MailConfig
from pylar.mail.drivers.log import LogTransport
from pylar.mail.drivers.memory import MemoryTransport
from pylar.mail.drivers.smtp import SmtpTransport
from pylar.mail.mailer import Mailer
from pylar.mail.transport import Transport


class MailServiceProvider(ServiceProvider):
    """Bind a :class:`Transport` and the :class:`Mailer` facade.

    The transport selection comes from :class:`MailConfig.driver`. If the
    user has not provided a MailConfig the provider falls back to a
    :class:`LogTransport` so the framework still ships with a working
    default that does not need any infrastructure.
    """

    def register(self, container: Container) -> None:
        container.singleton(Transport, self._make_transport)  # type: ignore[type-abstract]
        container.singleton(Mailer, self._make_mailer)

    def _make_transport(self) -> Transport:
        if not self.app.container.has(MailConfig):
            return LogTransport()
        config = self.app.container.make(MailConfig)
        if config.driver == "log":
            return LogTransport()
        if config.driver == "memory":
            return MemoryTransport()
        if config.driver == "smtp":
            return SmtpTransport(
                host=config.host,
                port=config.port,
                username=config.username,
                password=config.password,
                use_tls=config.use_tls,
                use_ssl=config.use_ssl,
                timeout=config.timeout,
            )
        raise ValueError(f"Unknown mail driver: {config.driver}")

    def _make_mailer(self) -> Mailer:
        from pylar.queue.dispatcher import Dispatcher

        transport = self.app.container.make(Transport)  # type: ignore[type-abstract]
        default_from = ""
        if self.app.container.has(MailConfig):
            default_from = self.app.container.make(MailConfig).default_from
        dispatcher: Dispatcher | None = None
        if self.app.container.has(Dispatcher):
            dispatcher = self.app.container.make(Dispatcher)
        return Mailer(
            transport,
            default_from=default_from,
            dispatcher=dispatcher,
        )
