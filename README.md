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
| `DEFITAXES_ETHERSCAN_API_KEY` | [Etherscan](https://etherscan.io)<sup>1</sup> - Ethereum (ETH) Blockchain Explorer |
| `DEFITAXES_BLOCKDAEMON_API_KEY` | [Blockdaemon](https://www.blockdaemon.com) - Blockdaemon Institutional Gateway to Web3 (Solana RPC) |
| `DEFITAXES_COINGECKO_API_KEY` | [CoinGecko](https://www.coingecko.com)<sup>2</sup> - Cryptocurrency prices |
| `DEFITAXES_TWELVEDATA_API_KEY` | [Twelve Data](https://twelvedata.com) - Fiat prices |
| `DEFITAXES_DEBANK_API_KEY` | [DeBank](https://cloud.debank.com)<sup>3</sup> - Current token balances, some protocol names |
| `DEFITAXES_RESERVOIR_API_KEY` | [Reservoir](https://reservoir.tools) - Currently held NFTs |
| `DEFITAXES_COVALENTHQ_API_KEY` | [CovalentHQ](https://goldrush.dev)<sup>4</sup>  - Fees on Arbitrum, errors on Fantom, some counterparty info on Ethereum |

<sup>1</sup> - "Free" plan does NOT support "BNB Smart Chain", Base, Optimism or Avalanche. These require the "Lite" plan $49/month.  
<sup>2</sup> - You can use either the CoinGecko "Demo" plan which is free, or the paid "Pro" plan.  
<sup>3</sup> - DeBank is prepaid only, minimum 200 USDC.  
<sup>4</sup> - GoldRush offer a 14-day fee trial, or paid plans start at $50/month.

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

---

## BittyTax Export API

A job-style REST API that automates the BittyTax export workflow: add wallet addresses, process all supported blockchains, generate a combined BittyTax Records XLSX file, and download it.

Because on-chain processing can take several minutes, the API uses a three-step pattern:

1. **Submit** — send your wallets and export options, receive a `job_id` immediately.
2. **Status** — poll until the job is `complete` or `failed`.
3. **Result** — download the XLSX file (allowed multiple times within 24 hours).

### Tunable constants

Two constants at the top of `app/views/export_job.py` control the limits:

| Constant | Default | Description |
| --- | --- | --- |
| `MAX_WALLETS` | `100` | Maximum number of wallet addresses per job |
| `JOB_RESULT_TTL_SECONDS` | `86400` | How long the result XLSX is retained (24 hours) |

---

### Authentication

All three endpoints require a Bearer token matching the `DEFITAXES_EXPORT_API_KEY` environment variable:

```
Authorization: Bearer <your-key>
```

Set the key in your `.env` file:

```
DEFITAXES_EXPORT_API_KEY=your-secret-key-here
```

If the key is absent or wrong the API returns `401`. If `DEFITAXES_EXPORT_API_KEY` is not set in the environment, all requests are rejected.

---

### POST `/api/export/submit`

Validates input synchronously and, if valid, starts processing in the background.

**Request body (JSON):**

```json
{
    "wallets": ["0xPrimaryAddress", "0xSecondaryAddress"],
    "currency": "USD",
    "is_macos": false,
    "export_options": {
        "transfer_in_known":    0,
        "transfer_in_unknown":  0,
        "transfer_out_known":   0,
        "transfer_out_unknown": 0
    }
}
```

| Field | Required | Description |
| --- | --- | --- |
| `wallets` | Yes | Array of wallet addresses. **First entry is the primary wallet.** Must contain 1–`MAX_WALLETS` unique, valid addresses (EVM `0x…` or Solana base58). |
| `currency` | No | Fiat currency for the report. Default `"USD"`. Supported: `USD`, `GBP`, `EUR`, `AUD`, `CAD`, `JPY`, `CHF`, `NZD`. |
| `is_macos` | No | Set to `true` when the XLSX will be opened on macOS. Default `false`. |
| `export_options` | No | BittyTax transfer mapping settings (same as the webpage export dialog). All fields default to `0`. |

**Transfer mapping values:**

| Value | Meaning for inbound | Meaning for outbound |
| --- | --- | --- |
| `0` | `Deposit` | `Withdrawal` |
| `1` | `Buy` | `Sell` |

**Response `200`:**

```json
{ "job_id": "550e8400-e29b-41d4-a716-446655440000" }
```

**Response `400`** (validation failure):

```json
{ "error": "Duplicate wallet addresses are not allowed" }
```

**Response `401`** (missing or wrong API key):

```json
{ "error": "Invalid or missing API key" }
```

**Response `409`** (primary address already processing):

```json
{ "error": "A job is already running for this address. Poll its status or wait before submitting a new one." }
```

---

### GET `/api/export/status?job_id=…&address=…`

Poll the job state.

| Query param | Description |
| --- | --- |
| `job_id` | ID returned by `/api/export/submit` |
| `address` | Primary wallet address (must match the address used at submit) |

**Response `200`:**

```json
{ "status": "processing" }
```

```json
{ "status": "complete" }
```

```json
{ "status": "failed", "error": "…detail…" }
```

| Status | Meaning |
| --- | --- |
| `processing` | Job is running — keep polling |
| `complete` | XLSX is ready to download |
| `failed` | Processing failed — see `error` field |

**Response `401`:** invalid or missing API key.  
**Response `403`:** address does not match the job's primary wallet.  
**Response `404`:** job not found or expired.

---

### GET `/api/export/result?job_id=…&address=…`

Download the generated BittyTax Records XLSX.

| Query param | Description |
| --- | --- |
| `job_id` | ID returned by `/api/export/submit` |
| `address` | Primary wallet address (must match the address used at submit) |

**Response `200`:** XLSX file attachment (`BittyTax_Records_{job_id}.xlsx`).

The file can be downloaded multiple times within the `JOB_RESULT_TTL_SECONDS` window (24 hours by default).

**Response `400`:** job not yet complete, or job failed.  
**Response `401`:** invalid or missing API key.  
**Response `403`:** address does not match the job's primary wallet.  
**Response `404`:** job not found or expired.  
**Response `410`:** job completed but the result file has since expired.

---

### Example workflow

```bash
# 1. Submit
curl -s -X POST http://localhost:5000/api/export/submit \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret-key-here" \
  -d '{
    "wallets": ["0xabc1234...", "0xdef5678..."],
    "currency": "GBP",
    "export_options": { "transfer_in_known": 1, "transfer_out_known": 1 }
  }'
# → {"job_id":"550e8400-e29b-41d4-a716-446655440000"}

# 2. Poll until complete
curl -s \
  -H "Authorization: Bearer your-secret-key-here" \
  "http://localhost:5000/api/export/status?job_id=550e8400-e29b-41d4-a716-446655440000&address=0xabc1234..."
# → {"status":"processing"}   (repeat until…)
# → {"status":"complete"}

# 3. Download
curl -OJ \
  -H "Authorization: Bearer your-secret-key-here" \
  "http://localhost:5000/api/export/result?job_id=550e8400-e29b-41d4-a716-446655440000&address=0xabc1234..."
# → saves BittyTax_Records_550e8400-e29b-41d4-a716-446655440000.xlsx
```

---

### Notes

- All submitted wallets are processed together in a single pass across all supported blockchains — the same behaviour as using the web interface.
- The combined XLSX contains transactions for all submitted wallets; all years are included (no tax-year filtering).
- Jobs older than `JOB_RESULT_TTL_SECONDS` are automatically expired by Redis (24 hours by default).
