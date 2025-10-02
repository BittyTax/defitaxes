# DeFi Taxes

This repository is a fork of [iraykhel/defitaxes](https://github.com/iraykhel/defitaxes), which its owner [iraykhel](https://github.com/iraykhel) is no longer able to maintain due to work constraints.

DeFi Taxes is a web-based application designed to help you calculate your crypto taxes using blockchain transaction data.

Many EVM blockchains are supported (e.g., Ethereum, BNB Smart Chain, Base, Arbitrum, Polygon, etc.) as well as Solana. See the [supported chains list](https://defitaxes.us/chains.html) for the full list.

If you would like to contribute to this project, follow the instructions below to set up a development server.

---

## Dependencies

### Python

You will need Python installed. See the [official Python website](https://www.python.org/downloads/) for installation instructions.

### Redis

Redis is used for storing user sessions and managing the process queue.

To install Redis, follow the [Redis installation instructions](https://redis.io/docs/latest/operate/oss_and_stack/install/install-redis/).

Details of your Redis server should be added to the `REDIS_URL` configuration parameter. See the [Config](#config) section for more details.

All keys stored in Redis are prefixed to make them easier to identify, especially if you are sharing a Redis server with other applications. The prefix is defined by the `REDIS_PREFIX` configuration parameter.

---

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/BittyTax/defitaxes.git
   ```

2. Create a virtual environment for Python. This is optional but recommended.
   ```bash
   cd defitaxes
   python -m venv .venv
   source .venv/bin/activate
   ```

3. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```

4. Create a `.env` file. See the [Environment Variables](#environment-variables) section for details.

5. To run the development server:
   ```bash
   flask run
   ```

By default, Flask will assume all application data is held in a folder called `instance`. If you prefer to use a different location, set this using the environment variable `DEFITAXES_INSTANCE_PATH`.

---

## Command Line Interface

To run the application without a web server, you can use the Flask command:
```bash
flask driver process <address> <chain>
```

For example:
```bash
flask driver process 0x032b7d93aeed91127baa55ad570d88fd2f15d589 ETH
```

---

## Environment Variables

Copy the [sample.env](https://github.com/BittyTax/defitaxes/blob/main/sample.env) file to `.env` and populate it with your API keys.

API keys can mostly be obtained for free by subscribing to the websites listed below. See footnotes for exceptions.

| Name | Description |
| --- | --- |
| `DEFITAXES_ETHERSCAN_API_KEY` | [Etherscan](https://etherscan.io) - Ethereum (ETH) Blockchain Explorer |
| `DEFITAXES_BLOCKDAEMON_API_KEY` | [Blockdaemon](https://www.blockdaemon.com) - Blockdaemon Institutional Gateway to Web3 (Solana RPC) |
| `DEFITAXES_COINGECKO_API_KEY` | [CoinGecko](https://www.coingecko.com)<sup>1</sup> - Cryptocurrency prices |
| `DEFITAXES_TWELVEDATA_API_KEY` | [Twelve Data](https://twelvedata.com) - Fiat prices |
| `DEFITAXES_DEBANK_API_KEY` | [DeBank](https://cloud.debank.com)<sup>2</sup> - Current token balances, some protocol names |
| `DEFITAXES_RESERVOIR_API_KEY` | [Reservoir](https://reservoir.tools) - Currently held NFTs |
| `DEFITAXES_COVALENTHQ_API_KEY` | [CovalentHQ](https://goldrush.dev)<sup>3</sup>  - Fees on Arbitrum, errors on Fantom, some counterparty info on Ethereum |

<sup>1</sup> - You can use either the CoinGecko "Demo" plan which is free, or the paid "Pro" plan.  
<sup>2</sup> - DeBank is prepaid only, minimum 200 USDC.  
<sup>3</sup> - GoldRush offer a 14-day fee trial, or paid plans start at $50/month.

---

## Config

The application configuration is loaded into Flask using a [Config](https://github.com/BittyTax/defitaxes/blob/main/config.py) object.

| Name | Default | Description |
| --- | --- | --- |
| `DEBUG_LEVEL` | `0` | Enable additional debug logging stored in the `instance/logs` folder |
| `REDIS_URL` | `"redis://localhost:6379"` | URL of Redis server |
| `REDIS_PREFIX` | `"defitaxes"` | Prefix added to all Redis keys |
| `SOLANA_MAX_TX` | `10000` | Maximum number of Solana transactions to be processed. Used to restrict API usage. Remove this parameter to remove the limit |
| `COINGECKO_PRO` | `False` | Choose between the "Pro" paid plan, or the "Demo" free plan |

---

## Databases

The application requires two pre-configured SQLite databases. These reside in the `instance` folder unless otherwise configured.

They have been removed from the repository due to size, but can be created manually.

### addresses.db

This database contains address labels for each blockchain. It is mainly created by scrapping content from the [Label Cloud](https://etherscan.io/labelcloud) of each EVM Block Explorer.

For Solana, the program labels are parsed using this Solscan [file](https://raw.githubusercontent.com/solscanofficial/labels/main/labels.json).

The code which creates this database is currently a separate repository. See [blockchain-address-database](https://github.com/BittyTax/blockchain-address-database).

### db.db

This database contains:

1. Fiat prices from [Twelve Data](https://twelvedata.com)
2. Crypto prices and data from [CoinGecko](https://www.coingecko.com)
3. EVM signature mappings from [4Byte](https://www.4byte.directory)

I will add Flask commands to initialise and create these tables.
