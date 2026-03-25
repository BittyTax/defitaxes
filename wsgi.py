import logging
import os
import socket
from datetime import datetime
from logging.handlers import RotatingFileHandler, SMTPHandler
from typing import Any

from flask_apscheduler import APScheduler
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.coingecko import CoinGecko
from app.constants import APP_NAME
from config import Config
from driver import driver

instance_path = os.environ.get("DEFITAXES_INSTANCE_PATH")

application = create_app(Config, instance_path)
application.register_blueprint(driver)


class ContextualSMTPHandler(SMTPHandler):
    """SMTP Handler that includes level, hostname, module and timestamp in the subject."""

    def getSubject(self, record):
        """Override to add level, module and timestamp to subject."""
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
        hostname = socket.gethostname()
        module = f"{record.name}.{record.module}" if record.module else record.name
        return f"{record.levelname} {APP_NAME}:{module} @ {timestamp} ({hostname})"


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
    rotate_handler.setLevel(application.config.get("LOG_LEVEL", logging.INFO))

    logger = logging.getLogger(application.name)
    logger.addHandler(rotate_handler)
    logger.setLevel(application.config.get("LOG_LEVEL", logging.INFO))

    logger = logging.getLogger("apscheduler")
    logger.addHandler(rotate_handler)

    logger = logging.getLogger("werkzeug")
    logger.addHandler(rotate_handler)

    if application.config.get("MAIL_FROM"):
        mail_handler = ContextualSMTPHandler(
            mailhost=("127.0.0.1", 25),
            fromaddr=application.config["MAIL_FROM"],
            toaddrs=application.config["MAIL_ALERTS"],
            subject="",  # Will be overridden by getSubject
            credentials=None,
            secure=None,
        )
        mail_handler.setLevel(logging.ERROR)
        mail_handler.setFormatter(formatter)

        logger = logging.getLogger(application.name)
        logger.addHandler(mail_handler)

        application.logger.info("SMTP email handler configured for error logging")

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

    if os.environ.get("DEV_USER"):

        class DevAuthMiddleware:  # pylint: disable=too-few-public-methods
            def __init__(self, app: Any) -> None:
                self.app = app

            def __call__(self, environ: dict[str, Any], start_response: Any) -> Any:
                test_user = os.environ.get("DEV_USER", "testuser")
                environ["HTTP_X_REMOTE_USER"] = test_user
                return self.app(environ, start_response)

        application.wsgi_app = DevAuthMiddleware(  # type: ignore[method-assign]
            application.wsgi_app
        )
        application.logger.info("Adding basic auth user: %s", os.environ.get("DEV_USER"))

# Assumes Nginx is acting as a reverse proxy.
application.wsgi_app = ProxyFix(  # type: ignore[method-assign]
    application.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)
