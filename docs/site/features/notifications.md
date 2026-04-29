# Notifications

Pylar's notification system delivers a single piece of information through multiple channels -- mail, log, database, or any custom channel you implement.

## Creating a notification

Subclass `Notification` and declare which channels it uses via the `via()` method. Each channel looks for a corresponding `to_<channel>()` renderer on the notification:

```python
from pylar.notifications import Notification, Notifiable
from pylar.mail import Mailable


class InvoicePaid(Notification):
    def __init__(self, invoice_id: int, amount: float) -> None:
        self.invoice_id = invoice_id
        self.amount = amount

    def via(self) -> tuple[str, ...]:
        return ("mail", "log")

    def to_mail(self, notifiable: Notifiable) -> Mailable:
        return Mailable(
            to=notifiable.routes_for("mail") or "",
            subject=f"Invoice #{self.invoice_id} paid",
            html=f"<p>Payment of ${self.amount:.2f} received.</p>",
        )

    def to_log(self, notifiable: Notifiable) -> str:
        return f"Invoice #{self.invoice_id} paid: ${self.amount:.2f}"
```

## The Notifiable protocol

Any object that implements `routes_for(channel: str) -> str | None` satisfies the `Notifiable` protocol. Returning `None` opts that recipient out of the channel:

```python
from pylar.notifications import Notifiable


class User:
    def __init__(self, email: str, name: str) -> None:
        self.email = email
        self.name = name

    def routes_for(self, channel: str) -> str | None:
        if channel == "mail":
            return self.email
        if channel == "log":
            return self.name
        return None
```

## Sending notifications

Resolve `NotificationDispatcher` from the container and call `send()`:

```python
from pylar.notifications import NotificationDispatcher

dispatcher = container.make(NotificationDispatcher)
await dispatcher.send(user, InvoicePaid(invoice_id=42, amount=99.95))
```

The dispatcher iterates through each channel returned by `via()` in order. The first channel to raise aborts the rest of the chain so failures are never silently swallowed.

## Built-in channels

### MailChannel

Calls `notification.to_mail(notifiable)` and passes the returned `Mailable` to the bound `Mailer`. Register it in your service provider:

```python
from pylar.notifications import MailChannel
from pylar.mail import Mailer

mail_channel = MailChannel(mailer=container.make(Mailer))
dispatcher.register_channel(mail_channel)
```

### LogChannel

Calls `notification.to_log(notifiable)` (if present) and writes the result through Python's `logging` module. Falls back to printing the notification class name when `to_log()` is not defined:

```python
from pylar.notifications import LogChannel

dispatcher.register_channel(LogChannel())
```

## Queued notifications

Set `should_queue = True` on the notification class and implement `to_payload()` / `from_payload()` to enable asynchronous delivery via the queue layer. The dispatcher serialises the notification into a `DeliverNotificationJob` and returns immediately:

```python
from pylar.notifications import Notification
from pylar.queue import JobPayload


class SlowReport(Notification):
    should_queue = True
    payload_type = ReportPayload

    def via(self) -> tuple[str, ...]:
        return ("mail",)

    def to_payload(self, notifiable: Notifiable) -> ReportPayload:
        return ReportPayload(user_id=..., report_id=...)

    @classmethod
    def from_payload(cls, container, payload):
        ...
```

## Testing

Use the built-in fake dispatcher to capture sent notifications without delivering them:

```python
fake = NotificationDispatcher.fake()
container.instance(NotificationDispatcher, fake)

await some_action()

assert len(fake.sent) == 1
```
