# Mail

Pylar's mail module provides typed mailables with HTML/Markdown templates, file attachments, queueable delivery, and pluggable transports.

## Defining a Mailable

### ViewMailable (Jinja templates)

```python
from pylar.mail import ViewMailable, Attachment
from pylar.views import View

class WelcomeMail(ViewMailable):
    html_template = "emails/welcome.html"
    text_template = "emails/welcome.txt"  # optional — auto-stripped from HTML if omitted

    def __init__(self, user: User) -> None:
        super().__init__(view)
        self.user = user

    def recipients(self) -> tuple[str, ...]:
        return (self.user.email,)

    def subject(self) -> str:
        return f"Welcome, {self.user.name}!"

    def context(self) -> dict:
        return {"user": self.user}
```

### MarkdownMailable

```python
from pylar.mail import MarkdownMailable

class ChangelogMail(MarkdownMailable):
    def recipients(self) -> tuple[str, ...]:
        return (self.user.email,)

    def subject(self) -> str:
        return "What's new this week"

    def markdown(self) -> str:
        return "# Changelog\n\n- Feature A\n- Bug fix B"
```

Markdown is rendered to HTML automatically via the `markdown` package.

## Attachments

```python
from pylar.mail import Attachment

class InvoiceMail(ViewMailable):
    html_template = "emails/invoice.html"

    def attachments(self) -> tuple[Attachment, ...]:
        return (
            Attachment(filename="invoice.pdf", content=pdf_bytes, content_type="application/pdf"),
            # Inline image referenced as cid:logo in the template:
            Attachment(filename="logo.png", content=logo_bytes, inline=True, cid="logo"),
        )
```

## Sending Mail

```python
from pylar.mail import Mailer

mailer: Mailer  # auto-wired

# Send immediately:
message = await mailer.send(WelcomeMail(user))

# Send via the queue (background):
record = await mailer.queue(WelcomeMail(user))

# Delayed send:
from datetime import timedelta
await mailer.queue(WelcomeMail(user), delay=timedelta(minutes=5))
```

## Transports

| Transport | Description |
|---|---|
| `MemoryTransport` | Captures messages in `.sent` list — for testing |
| `LogTransport` | Writes message details to a `logging.Logger` |
| `SmtpTransport` | Real SMTP delivery via stdlib `smtplib` (wrapped in `to_thread`) |

### SMTP Configuration

```python
from pylar.mail import SmtpTransport

transport = SmtpTransport(
    host="smtp.example.com",
    port=587,
    username="apikey",
    password="secret",
    use_tls=True,
)
```

### Custom Transport

Implement the `Transport` protocol:

```python
from pylar.mail import Transport, Message

class SesTransport:
    async def send(self, message: Message) -> None:
        # Send via AWS SES, SendGrid, etc.
        ...
```

## Testing

```python
from pylar.mail import Mailer

fake = Mailer.fake()
await fake.send(WelcomeMail(user))

assert len(fake.transport.sent) == 1
assert fake.transport.sent[0].to == ("user@example.com",)
fake.transport.clear()
```

## Message Model

The `Message` is a frozen Pydantic model with fields: `to`, `subject`, `html`, `text`, `from_address`, `cc`, `bcc`, `reply_to`, `attachments`. It is returned by `mailer.send()` for inspection.
