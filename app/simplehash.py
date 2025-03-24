import time
import traceback
from datetime import datetime

import requests
from flask import current_app

from .imports import Import
from .util import log, log_error, normalize_address


def get_nft_balances_simplehash(all_chains, current_import, progress_bar=None):
    session = requests.session()
    session.headers.update({"X-API-Key": current_app.config["SIMPLEHASH_API_KEY"]})

    simplehash_chains = [
        cd
        for name, cd in all_chains.items()
        if not cd["is_upload"] and "simplehash_mapping" in cd["chain"].CONFIG[name]
    ]

    for chain_data in simplehash_chains:
        chain = chain_data["chain"]
        accepted_addresses = [
            normalize_address(a) for a in chain_data["import_addresses"] if chain.check_validity(a)
        ]
        if not accepted_addresses:
            continue

        simplehash_chain_id = chain.CONFIG[chain.name]["simplehash_mapping"]
        url = (
            f"https://api.simplehash.com/api/v0/nfts/owners?chains={simplehash_chain_id}"
            f"&wallet_addresses={','.join(accepted_addresses)}"
            f"&queried_wallet_balances=1&count=1"
        )
        done = False
        page_idx = 0

        if progress_bar:
            progress_bar.update(f"SimpleHash: Retrieving your NFTs on {chain.name}", 0)

        try:
            while not done:
                time.sleep(0.2)
                log("SimpleHash URL", url)
                resp = session.get(url, timeout=15)
                if resp.status_code != 200:
                    log_error("Failed to retrieve NFT data", url, resp.content)
                    break

                data = resp.json()
                # log(
                #    "post dump",
                #    url,
                #    json.dumps(data, indent=4),
                #    filename="simplehash.txt",
                # )

                total_count = data["count"]
                total_pages = (total_count // 50) + 1

                if progress_bar:
                    progress_bar.update(
                        f"SimpleHash: Retrieving your NFTs on {chain.name}: "
                        f"{page_idx + 1}/{total_pages}",
                        3.0 / len(simplehash_chains) / total_pages,
                    )

                entries = data["nfts"]
                for entry in entries:
                    _process_simplehash_entry(entry, chain.name, chain_data)

                if len(entries) < 50 or data.get("next") is None:
                    done = True
                else:
                    url = data["next"]
                page_idx += 1
        except (requests.exceptions.RequestException, ValueError):
            current_import.add_error(
                Import.SIMPLEHASH_FAILURE, chain=chain, debug_info=traceback.format_exc()
            )
            log_error(chain.name, ": Failed to get_current_tokens:NFTs")


def _process_simplehash_entry(entry, chain_name, chain_data):
    contract_address = normalize_address(entry["contract_address"])
    nft_id = entry["token_id"]
    symbol = entry["contract"]["symbol"]
    nft_type = entry["contract"]["type"]

    # Skip unsupported ERC1155 tokens on specific chains
    if chain_name in ["BSC", "Polygon", "Fantom", "zkEVM"] and nft_type == "ERC1155":
        return

    for bal in entry["queried_wallet_balances"]:
        amount = bal["quantity"]
        owner = normalize_address(bal["address"])
        first_acquired = bal["first_acquired_date"][:19]
        try:
            first_acquired_ts = int(
                datetime.strptime(first_acquired, "%Y-%m-%dT%H:%M:%S").timestamp()
            )
        except ValueError as e:
            log_error("Failed to convert SimpleHash timestamp", first_acquired, str(e))
            first_acquired_ts = None

        if owner not in chain_data["current_tokens"] or chain_data["current_tokens"][owner] is None:
            chain_data["current_tokens"][owner] = {}

        ct = chain_data["current_tokens"][owner]
        if contract_address not in ct or "nft_amounts" not in ct[contract_address]:
            ct[contract_address] = {
                "symbol": symbol,
                "nft_amounts": {},
                "acquisitions": {},
                "type": nft_type,
            }

        ct[contract_address]["nft_amounts"][nft_id] = amount
        ct[contract_address]["acquisitions"][nft_id] = first_acquired_ts
        log(
            "SimpleHash acquisition",
            contract_address,
            nft_type,
            symbol,
            nft_id,
            amount,
            first_acquired_ts,
        )

        floor_prices = entry["collection"]["floor_prices"]
        for fp in floor_prices:
            if (
                fp["marketplace_id"] == "opensea"
                and fp["payment_token"]["payment_token_id"] == "ethereum.native"
            ):
                eth_floor_rate = fp["value"] / float(pow(10, 18))
                ct[contract_address]["eth_floor"] = eth_floor_rate

                log("SimpleHash floor_rate", eth_floor_rate)

    # log(
    #   "current tokens",
    #    chain_data["current_tokens"],
    #    filename="simplehash.txt",
    # )
