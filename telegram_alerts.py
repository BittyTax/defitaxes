import asyncio
import logging
import os
import time

from telethon import TelegramClient


class TelegramAlertsHandler(logging.Handler):
    MAX_ALERTS_PER_MINUTE = 5
    ALERT_COOLDOWN_SECONDS = 60

    def __init__(self):
        super().__init__(logging.ERROR)
        self.alert_timestamps = []
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.client = TelegramClient(
            "bot",
            os.environ.get("DEFITAXES_TELEGRAM_API_ID"),
            os.environ.get("DEFITAXES_TELEGRAM_API_HASH"),
        )
        self.client.start(bot_token=os.environ.get("DEFITAXES_TELEGRAM_BOT_TOKEN"))

        self.loop.run_until_complete(
            self._get_entity(os.environ.get("DEFITAXES_TELEGRAM_ALERT_USER"))
        )

    def emit(self, record):
        current_time = time.time()

        self.alert_timestamps = [
            ts for ts in self.alert_timestamps if current_time - ts < self.ALERT_COOLDOWN_SECONDS
        ]

        if len(self.alert_timestamps) >= self.MAX_ALERTS_PER_MINUTE:
            return

        self.alert_timestamps.append(current_time)
        message = self.format(record)
        self.loop.run_until_complete(self._send_message(message))

    async def _get_entity(self, username):
        if not self.client.is_connected():
            return

        self.peer = await self.client.get_entity(username)

    async def _send_message(self, message):
        if not self.client.is_connected():
            return

        await self.client.send_message(self.peer, message)
