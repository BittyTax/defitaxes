# -*- coding: utf-8 -*-
import os

import dotenv

dotenv.load_dotenv()
basedir = os.path.abspath(os.path.dirname(__file__))


class Config:  # pylint: disable=too-few-public-methods
    os.environ["debug"] = "0"
    os.environ["version"] = "1.42"

    DATA_DIR = os.path.join(basedir, "data")
    USERS_DIR = os.path.join(DATA_DIR, "users")
    LOGS_DIR = os.path.join(basedir, "logs")
