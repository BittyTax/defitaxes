import os

import dotenv

dotenv.load_dotenv()


class Config:  # pylint: disable=too-few-public-methods
    DEBUG_LEVEL = 0
    APP_VERSION = 1.42

    REDIS_URL = "redis://localhost:6379"
    REDIS_PREFIX = "defitaxes"

    ETHERSCAN_API_KEY = os.environ.get("DEFITAXES_ETHERSCAN_API_KEY", "")
    OPTIMISTIC_ETHERSCAN_API_KEY = os.environ.get("DEFITAXES_OPTIMISTIC_ETHERSCAN_API_KEY", "")
    BSCSCAN_API_KEY = os.environ.get("DEFITAXES_BSCSCAN_API_KEY", "")
    ARBISCAN_API_KEY = os.environ.get("DEFITAXES_ARBISCAN_API_KEY", "")
    NOVA_ARBISCAN_API_KEY = os.environ.get("DEFITAXES_NOVA_ARBISCAN_API_KEY", "")
    POLYGONSCAN_API_KEY = os.environ.get("DEFITAXES_POLYGONSCAN_API_KEY", "")
    ZKEVM_POLYGONSCAN_API_KEY = os.environ.get("DEFITAXES_ZKEVM_POLYGONSCAN_API_KEY", "")
    SNOWTRACE_API_KEY = os.environ.get("DEFITAXES_SNOWTRACE_API_KEY", "")
    FTMSCAN_API_KEY = os.environ.get("DEFITAXES_FTMSCAN_API_KEY", "")
    CRONOSCAN_API_KEY = os.environ.get("DEFITAXES_CRONOSCAN_API_KEY", "")
    CELOSCAN_API_KEY = os.environ.get("DEFITAXES_CELOSCAN_API_KEY", "")
    MOONSCAN_API_KEY = os.environ.get("DEFITAXES_MOONSCAN_API_KEY", "")
    MOONRIVER_MOONSCAN_API_KEY = os.environ.get("DEFITAXES_MOONRIVER_MOONSCAN_API_KEY", "")
    GNOSISSCAN_API_KEY = os.environ.get("DEFITAXES_GNOSISSCAN_API_KEY", "")
    BASESCAN_API_KEY = os.environ.get("DEFITAXES_BASESCAN_API_KEY", "")

    BLOCKDAEMON_API_KEY = os.environ.get("DEFITAXES_BLOCKDAEMON_API_KEY", "")  # Solana RPC
    SOLANA_MAX_TX = 10000

    COINGECKO_API_KEY = os.environ.get("DEFITAXES_COINGECKO_API_KEY", "")
    COINGECKO_PRO = False

    TWELVEDATA_API_KEY = os.environ.get("DEFITAXES_TWELVEDATA_API_KEY", "")
    DEBANK_API_KEY = os.environ.get("DEFITAXES_DEBANK_API_KEY", "")
    SIMPLEHASH_API_KEY = os.environ.get("DEFITAXES_SIMPLEHASH_API_KEY", "")
    COVALENTHQ_API_KEY = os.environ.get("DEFITAXES_COVALENTHQ_API_KEY", "")
