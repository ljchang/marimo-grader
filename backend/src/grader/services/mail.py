"""Outbound transactional email.

One small abstraction over three transports so nothing else in the service
imports ``smtplib``:

* ``smtp``    - a real relay. Amazon SES is reached through its SMTP interface,
  so switching providers is configuration, not code.
* ``console`` - writes the message to the log. The default, and what
  development uses; nothing leaves the machine.
* ``memory``  - collects messages in ``outbox`` for the test suite.

The mailer is resolved once from settings and cached. Tests call
:func:`reset_mailer` after changing configuration.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from functools import lru_cache
from typing import Protocol

from grader.config import get_settings

log = logging.getLogger("grader.mail")


class MailError(RuntimeError):
    """Delivery failed. Callers decide whether that is fatal."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str | None = None


def _build(msg: Message, sender: str, reply_to: str | None) -> EmailMessage:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = msg.to
    m["Subject"] = msg.subject
    if reply_to:
        m["Reply-To"] = reply_to
    # Transactional mail should never be auto-replied to or filed as bulk.
    m["Auto-Submitted"] = "auto-generated"
    m.set_content(msg.text)
    if msg.html:
        m.add_alternative(msg.html, subtype="html")
    return m


class Mailer(Protocol):
    def send(self, msg: Message) -> None: ...


@dataclass
class SMTPMailer:
    host: str
    port: int
    username: str | None
    password: str | None
    sender: str
    reply_to: str | None = None
    starttls: bool = True
    timeout: int = 20

    def send(self, msg: Message) -> None:
        built = _build(msg, self.sender, self.reply_to)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
                if self.starttls:
                    smtp.starttls()
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.send_message(built)
        except (smtplib.SMTPException, OSError) as e:
            raise MailError(f"{type(e).__name__}: {e}") from e
        log.info("mail sent to=%s subject=%r", msg.to, msg.subject)


@dataclass
class ConsoleMailer:
    sender: str
    reply_to: str | None = None

    def send(self, msg: Message) -> None:
        log.warning(
            "mail NOT sent (transport=console)\nFrom: %s\nTo: %s\nSubject: %s\n\n%s",
            self.sender,
            msg.to,
            msg.subject,
            msg.text,
        )


@dataclass
class MemoryMailer:
    sender: str = "grader@example.test"
    reply_to: str | None = None
    outbox: list[Message] = field(default_factory=list)

    def send(self, msg: Message) -> None:
        self.outbox.append(msg)


@lru_cache
def mailer() -> Mailer:
    s = get_settings()
    if s.mail_transport == "smtp":
        if not s.smtp_host:
            raise MailError("GRADER_MAIL_TRANSPORT=smtp but GRADER_SMTP_HOST is unset")
        return SMTPMailer(
            host=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_username,
            password=s.smtp_password,
            sender=s.mail_from,
            reply_to=s.mail_reply_to,
            starttls=s.smtp_starttls,
        )
    if s.mail_transport == "memory":
        return MemoryMailer(sender=s.mail_from, reply_to=s.mail_reply_to)
    return ConsoleMailer(sender=s.mail_from, reply_to=s.mail_reply_to)


def reset_mailer() -> None:
    """Drop the cached mailer (tests, or after a settings change)."""
    mailer.cache_clear()


def send(msg: Message) -> None:
    mailer().send(msg)
