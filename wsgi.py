import os

from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.util import log
from config import Config
from driver import driver

app = create_app(Config)
app.register_blueprint(driver)

with app.app_context():
    log("env check", os.environ.get("api_key_etherscan"), filename="env_check.txt")

# Assumes Nginx is acting as a reverse proxy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
