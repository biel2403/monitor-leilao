from __future__ import annotations

import logging
import smtplib
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Protocol

from auction_monitor.config import Settings
from auction_monitor.database import Database

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    channel: str

    def send(self, message: str) -> tuple[bool, str | None]:
        ...


class TelegramNotifier:
    channel = "telegram"

    def __init__(self, token: str | None, chat_id: str | None):
        self.token = token
        self.chat_id = chat_id

    def send(self, message: str) -> tuple[bool, str | None]:
        if not self.token or not self.chat_id:
            return False, "Telegram nao configurado"
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": self.chat_id, "text": message, "disable_web_page_preview": "false"}).encode()
        try:
            with urllib.request.urlopen(url, data=data, timeout=15) as response:
                if response.status >= 400:
                    return False, f"HTTP {response.status}"
            return True, None
        except Exception as exc:  # external service boundary
            logger.warning("Falha ao enviar Telegram: %s", exc)
            return False, str(exc)


class EmailNotifier:
    channel = "email"

    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, message: str) -> tuple[bool, str | None]:
        if not self.settings.smtp_host or not self.settings.smtp_from or not self.settings.smtp_to:
            return False, "E-mail nao configurado"
        email = EmailMessage()
        email["Subject"] = "Oportunidade em leilao"
        email["From"] = self.settings.smtp_from
        email["To"] = self.settings.smtp_to
        email.set_content(message)
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
                if self.settings.smtp_use_tls:
                    smtp.starttls()
                if self.settings.smtp_username and self.settings.smtp_password:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(email)
            return True, None
        except Exception as exc:  # external service boundary
            logger.warning("Falha ao enviar e-mail: %s", exc)
            return False, str(exc)


def build_notifiers(settings: Settings) -> dict[str, Notifier]:
    return {
        "telegram": TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id),
        "email": EmailNotifier(settings),
    }


def format_opportunity_message(opportunity: dict, lot: dict, filter_name: str) -> str:
    lines = [
        "NOVO LOTE",
        "",
        str(lot.get("title") or ""),
        "",
        f"Lance atual: {format_money(lot.get('current_bid'))}",
        f"Local: {format_location(lot)}",
        f"Encerramento: {lot.get('closes_at') or 'Nao informado'}",
        f"Filtro: {filter_name}",
        "",
        "Criterios correspondidos:",
    ]
    for criterion in opportunity.get("matched_criteria") or []:
        lines.append(f"- {criterion}")
    discount = opportunity.get("discount_percent")
    if discount is not None:
        lines.append(f"- Desconto calculado: {discount:.2f}%")
    lines.extend(["", "Ver lote:", str(lot.get("url") or "")])
    return "\n".join(lines)


def dispatch_notifications(db: Database, opportunity_id: int, channels: list[str], message: str, notifiers: dict[str, Notifier]) -> int:
    recorded = 0
    for channel in channels:
        if db.notification_exists(opportunity_id, channel):
            continue
        notifier = notifiers.get(channel)
        if notifier is None:
            db.record_notification(opportunity_id, channel, "skipped", message, "Canal desconhecido")
            recorded += 1
            continue
        ok, error = notifier.send(message)
        db.record_notification(opportunity_id, channel, "sent" if ok else "failed", message, error)
        recorded += 1
    return recorded


def format_money(value: object) -> str:
    if value in (None, ""):
        return "Nao informado"
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_location(lot: dict) -> str:
    city = lot.get("city")
    state = lot.get("state")
    if city and state:
        return f"{city}/{state}"
    return city or state or "Nao informado"
