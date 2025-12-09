from typing import Optional

import redis
from flask import Flask

from config import Config

from .views.admin import admin
from .views.chains import chains
from .views.main import main
from .views.manual import manual_transactions
from .views.tax_calc import tax_calc
from .views.typing import typing
from .views.uploads import uploads


def create_app(config_class: type[Config], instance_path: Optional[str] = None) -> Flask:
    app = Flask(__name__, instance_path=instance_path)
    app.config.from_object(config_class)

    # Primary Redis client with decode_responses=True for text data
    app.extensions["redis"] = redis.Redis.from_url(
        str(app.config.get("REDIS_URL")), decode_responses=True
    )

    # Binary Redis client for binary data like Excel files
    app.extensions["redis_binary"] = redis.Redis.from_url(
        str(app.config.get("REDIS_URL")), decode_responses=False
    )

    app.register_blueprint(main)
    app.register_blueprint(chains)
    app.register_blueprint(tax_calc)
    app.register_blueprint(typing)
    app.register_blueprint(manual_transactions)
    app.register_blueprint(uploads)
    app.register_blueprint(admin)

    return app
