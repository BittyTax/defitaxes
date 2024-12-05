# -*- coding: utf-8 -*-
import os

import dotenv

from app.util import log


class Config:  # pylint: disable=too-few-public-methods
    dotenv.load_dotenv()
    os.environ["debug"] = "0"
    os.environ["version"] = "1.42"

    log("env check", os.environ.get("api_key_etherscan"), filename="env_check.txt")
