import dotenv

dotenv.load_dotenv()


class Config:  # pylint: disable=too-few-public-methods
    DEBUG_LEVEL = 0
    APP_VERSION = 1.42

    SOLANA_MAX_TX = 10000
