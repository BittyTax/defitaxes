import redis
from flask import Flask

from .views.admin import admin
from .views.chains import chains
from .views.main import main
from .views.manual import manual_transactions
from .views.tax_calc import tax_calc
from .views.typing import typing
from .views.uploads import uploads


def create_app(config_class) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    app.redis = redis.Redis.from_url(app.config.get("REDIS_URL"), decode_responses=True)

    app.register_blueprint(main)
    app.register_blueprint(chains)
    app.register_blueprint(tax_calc)
    app.register_blueprint(typing)
    app.register_blueprint(manual_transactions)
    app.register_blueprint(uploads)
    app.register_blueprint(admin)

    return app
