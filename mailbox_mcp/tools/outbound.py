"""Outbound mail over implicit-TLS SMTP."""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Final

from message_compose import COMPOSE_PROPERTIES, compose, envelope_recipients
from tools.base import Tool

logger: Final[logging.Logger] = logging.getLogger(__name__)


class SendEmail(Tool):
    """Send a message immediately."""

    @property
    def name(self) -> str:
        return "send_email"

    @property
    def description(self) -> str:
        return "Send an email immediately from this mailbox. This is not reversible."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": COMPOSE_PROPERTIES,
            "required": ["to", "subject", "body"],
        }

    def run(self, arguments: dict[str, Any]) -> str:
        message: EmailMessage = compose(self._config.imap_user, arguments)
        recipients: list[str] = envelope_recipients(message)
        if not recipients:
            raise ValueError("no recipients resolved from the 'to' and 'cc' arguments")

        context: ssl.SSLContext = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        with smtplib.SMTP_SSL(
            host=self._config.smtp_host,
            port=self._config.smtp_port,
            context=context,
        ) as smtp:
            logged_in: tuple[int, bytes] = smtp.login(self._config.imap_user, self._config.password)
            logger.debug("SMTP login: %s", logged_in[0])
            refused: dict[str, tuple[int, bytes]] = smtp.send_message(message, to_addrs=recipients)
        if refused:
            return f"Sent, but {len(refused)} recipient(s) were refused: {sorted(refused)}"
        return f"Sent to {', '.join(recipients)}."
