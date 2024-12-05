# -*- coding: utf-8 -*-
from werkzeug.middleware.proxy_fix import ProxyFix

from app.app import app

app.config.from_object("config.Config")

# Assumes Nginx is acting as a reverse proxy.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
