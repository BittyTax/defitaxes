import logging
import os
from logging.handlers import RotatingFileHandler

from flask_apscheduler import APScheduler
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.coingecko import CoinGecko
from config import Config
from driver import driver
from telegram_alerts import TelegramAlertsHandler

instance_path = os.environ.get("DEFITAXES_INSTANCE_PATH")

application = create_app(Config, instance_path)
application.register_blueprint(driver)


def _coingecko_job():
    with application.app_context():
        application.logger.info("Starting CoinGecko symbols download job")
        cg = CoinGecko()
        cg.download_symbols()


with application.app_context():
    logfile = os.path.join(application.instance_path, "flask.log")
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s.%(module)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    rotate_handler = RotatingFileHandler(logfile, maxBytes=100 * 1024 * 1024, backupCount=5)
    rotate_handler.setFormatter(formatter)
    rotate_handler.setLevel(logging.DEBUG)

    telegram_handler = TelegramAlertsHandler()
    telegram_handler.setFormatter(formatter)

    logger = logging.getLogger(application.name)
    logger.addHandler(rotate_handler)
    logger.addHandler(telegram_handler)
    logger.setLevel(logging.DEBUG)

    logger = logging.getLogger("apscheduler")
    logger.addHandler(rotate_handler)
    logger.addHandler(telegram_handler)

    logger = logging.getLogger("werkzeug")
    logger.addHandler(rotate_handler)
    logger.addHandler(telegram_handler)

    scheduler = APScheduler()
    scheduler.init_app(application)
    scheduler.start()

    job = scheduler.add_job(
        id="_coingecko_job",
        func=_coingecko_job,
        trigger="interval",
        hours=application.config["COINGECKO_DOWNLOAD_PERIOD"],
        misfire_grace_time=600,  # Allow job to be executed up to 10 mins late
        coalesce=True,
        max_instances=1,
    )
    application.logger.info("Scheduled job: %s", job)

# Assumes Nginx is acting as a reverse proxy.
application.wsgi_app = ProxyFix(  # type: ignore[method-assign]
    application.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)
