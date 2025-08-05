import asyncio
import logging
import os
import time
from typing import List

from telethon import TelegramClient


class TelegramAlertsHandler(logging.Handler):
    MAX_ALERTS_PER_MINUTE = 5
    ALERT_COOLDOWN_SECONDS = 60

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.initialised = False
        self.alert_timestamps: List[float] = []

        try:
            api_id = os.environ.get("DEFITAXES_TELEGRAM_API_ID")
            api_hash = os.environ.get("DEFITAXES_TELEGRAM_API_HASH")
            bot_token = os.environ.get("DEFITAXES_TELEGRAM_BOT_TOKEN")
            username = os.environ.get("DEFITAXES_TELEGRAM_ALERT_USER")

            if not api_id or not api_hash or not bot_token or not username:
                return

            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            self.client = TelegramClient("bot", api_id, api_hash)
            self.client.start(bot_token=bot_token)

            self.loop.run_until_complete(self._get_entity(username))
            self.initialised = True

        except (ValueError, asyncio.TimeoutError, ConnectionError):
            self.initialised = False

    def emit(self, record: logging.LogRecord) -> None:
        if not self.initialised:
            return

        current_time = time.time()
        self.alert_timestamps = [
            ts for ts in self.alert_timestamps if current_time - ts < self.ALERT_COOLDOWN_SECONDS
        ]

        if len(self.alert_timestamps) >= self.MAX_ALERTS_PER_MINUTE:
            return

        self.alert_timestamps.append(current_time)
        message = self.format(record)
        self.loop.run_until_complete(self._send_message(message))

    async def _get_entity(self, username: str) -> None:
        if not self.client.is_connected():
            return
        self.peer = await self.client.get_entity(username)

    async def _send_message(self, message: str) -> None:
        if not self.client.is_connected():
            return
        await self.client.send_message(self.peer, message)
