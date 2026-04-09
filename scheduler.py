"""Standalone APScheduler process.

Run independently of Gunicorn so scheduled jobs don't duplicate across workers:
    python scheduler.py

Uses a minimal Flask app (no blueprints) — only needs config, logger, and
instance_path for the CoinGecko download job.
"""

import logging
import os
import socket
from datetime import datetime
from logging.handlers import RotatingFileHandler, SMTPHandler
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from flask import Flask

from app.coingecko import CoinGecko
from app.constants import APP_NAME
from config import config


def _create_app(config_name: str, instance_path: Optional[str]) -> Flask:
    app = Flask(__name__, instance_path=instance_path)
    app.config.from_object(config[config_name])
    return app


class ContextualSMTPHandler(SMTPHandler):
    def getSubject(self, record):
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        hostname = socket.gethostname()
        module = f"{record.name}.{record.module}" if record.module else record.name
        return f"{record.levelname} {APP_NAME}:{module} @ {timestamp} ({hostname})"


def _setup_logging(app: Flask) -> None:
    logfile = os.path.join(app.instance_path, "scheduler.log")
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s.%(module)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    rotate_handler = RotatingFileHandler(logfile, maxBytes=100 * 1024 * 1024, backupCount=5)
    rotate_handler.setFormatter(formatter)
    rotate_handler.setLevel(app.config.get("LOG_LEVEL", logging.INFO))

    for name in (app.name, "apscheduler"):
        logger = logging.getLogger(name)
        logger.addHandler(rotate_handler)
        logger.setLevel(app.config.get("LOG_LEVEL", logging.INFO))

    if app.config.get("MAIL_FROM"):
        mail_handler = ContextualSMTPHandler(
            mailhost=("127.0.0.1", 25),
            fromaddr=app.config["MAIL_FROM"],
            toaddrs=app.config["MAIL_ALERTS"],
            subject="",
            credentials=None,
            secure=None,
        )
        mail_handler.setLevel(logging.ERROR)
        mail_handler.setFormatter(formatter)
        logging.getLogger(app.name).addHandler(mail_handler)
        app.logger.info("SMTP email handler configured for error logging")


def _coingecko_job(app: Flask) -> None:
    with app.app_context():
        app.logger.info("Starting CoinGecko symbols download job")
        cg = CoinGecko()
        cg.download_symbols()


def main() -> None:
    instance_path = os.environ.get("DEFITAXES_INSTANCE_PATH")
    config_name = os.environ.get("FLASK_CONFIG", "development")

    app = _create_app(config_name, instance_path)

    with app.app_context():
        _setup_logging(app)
        app.logger.info("Scheduler starting, config: %s", config_name)

    scheduler = BlockingScheduler()
    job = scheduler.add_job(
        func=_coingecko_job,
        args=[app],
        trigger="interval",
        hours=app.config["COINGECKO_DOWNLOAD_PERIOD"],
        misfire_grace_time=600,
        coalesce=True,
        max_instances=1,
    )

    with app.app_context():
        app.logger.info("Scheduled job: %s", job)

    scheduler.start()


if __name__ == "__main__":
    main()
