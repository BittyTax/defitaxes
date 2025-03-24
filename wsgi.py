import os

from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.util import log
from config import Config
from driver import driver

instance_path = os.environ.get("DEFITAXES_INSTANCE_PATH")

application = create_app(Config, instance_path)
application.register_blueprint(driver)

with application.app_context():
    log("env check", os.environ.get("api_key_etherscan"), filename="env_check.txt")

# Assumes Nginx is acting as a reverse proxy.
application.wsgi_app = ProxyFix(  # type: ignore[method-assign]
    application.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1
)
