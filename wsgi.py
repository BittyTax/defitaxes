import logging
import os
from logging.handlers import RotatingFileHandler

from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from config import Config
from driver import driver
from telegram_alerts import TelegramAlertsHandler

instance_path = os.environ.get("DEFITAXES_INSTANCE_PATH")

application = create_app(Config, instance_path)
application.register_blueprint(driver)

with application.app_context():
    logfile = os.path.join(application.instance_path, "flask.log")
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    rotate_handler = RotatingFileHandler(logfile, maxBytes=10 * 1024 * 1024, backupCount=5)
    rotate_handler.setFormatter(formatter)
    rotate_handler.setLevel(logging.DEBUG)

    telegram_handler = TelegramAlertsHandler()
    telegram_handler.setFormatter(formatter)

    logger = logging.getLogger(application.name)
    logger.addHandler(rotate_handler)
    logger.addHandler(telegram_handler)
    logger.setLevel(logging.DEBUG)

    logger = logging.getLogger("werkzeug")
    logger.addHandler(rotate_handler)
    logger.addHandler(telegram_handler)

    application.logger.info(f"env check {application.config['ETHERSCAN_API_KEY']}")

# Assumes Nginx is acting as a reverse proxy.
application.wsgi_app = ProxyFix(  # type: ignore[method-assign]
    application.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)
