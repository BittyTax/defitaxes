import os

import dotenv

dotenv.load_dotenv()


class Config:  # pylint: disable=too-few-public-methods
    DEBUG_LEVEL = 0
    APP_VERSION = 1.43

    REDIS_URL = "redis://localhost:6379"
    REDIS_PREFIX = "defitaxes"

    ETHERSCAN_API_KEY = os.environ.get("DEFITAXES_ETHERSCAN_API_KEY", "")
    BLOCKDAEMON_API_KEY = os.environ.get("DEFITAXES_BLOCKDAEMON_API_KEY", "")  # Solana RPC
    SOLANA_MAX_TX = 10000

    COINGECKO_API_KEY = os.environ.get("DEFITAXES_COINGECKO_API_KEY", "")
    COINGECKO_PRO = False

    TWELVEDATA_API_KEY = os.environ.get("DEFITAXES_TWELVEDATA_API_KEY", "")
    DEBANK_API_KEY = os.environ.get("DEFITAXES_DEBANK_API_KEY", "")
    RESERVOIR_API_KEY = os.environ.get("DEFITAXES_RESERVOIR_API_KEY")
    COVALENTHQ_API_KEY = os.environ.get("DEFITAXES_COVALENTHQ_API_KEY", "")
