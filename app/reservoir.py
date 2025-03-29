import json
import time
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

import requests
from flask import current_app

from .chain import ChainData
from .constants import ETH_NULL_ADDRESS
from .imports import Import
from .redis_wrap import ProgressBar
from .util import log, log_error, normalize_address


def get_nft_balances_reservoir(
    all_chains: Dict[str, ChainData],
    current_import: Import,
    progress_bar: Optional[ProgressBar] = None,
):
    session = requests.session()
    session.headers.update({"X-API-Key": current_app.config["RESERVOIR_API_KEY"]})

    reservoir_chains = [
        cd
        for name, cd in all_chains.items()
        if not cd["is_upload"] and "reservoir_mapping" in cd["chain"].CONFIG[name]
    ]

    for chain_data in reservoir_chains:
        chain = chain_data["chain"]
        accepted_addresses = [
            normalize_address(a) for a in chain_data["import_addresses"] if chain.check_validity(a)
        ]

        for address in accepted_addresses:
            reservoir_chain_id = chain.CONFIG[chain.name]["reservoir_mapping"]
            if reservoir_chain_id:
                base_url = f"https://api-{reservoir_chain_id}.reservoir.tools"
            else:
                # Ethereum URL
                base_url = "https://api.reservoir.tools"

            limit = 200
            url: Optional[str] = f"{base_url}/users/{address}/tokens/v10?limit={limit}"

            if progress_bar:
                progress_bar.update(
                    f"Reservoir: Retrieving your NFTs on {chain.name} for {address}",
                    1.0 / len(accepted_addresses),
                )

            try:
                while url:
                    time.sleep(0.5)
                    log("Reservoir URL", url)
                    resp = session.get(url, timeout=15)
                    resp.raise_for_status()
                    data = resp.json()

                    log(
                        "post dump",
                        url,
                        json.dumps(data, indent=4),
                        filename="reservoir.txt",
                    )

                    entries = data["tokens"]
                    for entry in entries:
                        _process_reservoir_entry(entry, chain.name, chain_data, address)

                    continuation = data.get("continuation")
                    if continuation:
                        url = (
                            f"{base_url}/users/{address}/tokens/v10"
                            f"?continuation={continuation}&limit={limit}"
                        )
                    else:
                        url = None
            except (requests.exceptions.RequestException, ValueError):
                current_import.add_error(
                    Import.RESERVOIR_FAILURE, chain=chain, debug_info=traceback.format_exc()
                )
                log_error(chain.name, ": Failed to get_current_tokens:NFTs")


def _process_reservoir_entry(entry: Any, chain_name: str, chain_data: ChainData, address: str):
    contract_address = normalize_address(entry["token"]["contract"])
    nft_id = entry["token"]["tokenId"]
    symbol = entry["token"]["collection"]["symbol"]
    nft_type = entry["token"]["kind"].upper()

    # Skip unsupported ERC1155 tokens on specific chains
    if chain_name in ["BSC", "Polygon", "Fantom", "zkEVM"] and nft_type == "ERC1155":
        return

    amount = entry["ownership"]["tokenCount"]
    owner = normalize_address(address)
    first_acquired = entry["ownership"]["acquiredAt"]

    try:
        first_acquired_ts = int(
            datetime.strptime(first_acquired, "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()
        )
    except ValueError as e:
        log_error("Failed to convert Reservoir timestamp", first_acquired, str(e))
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
        "Reservoir acquisition",
        contract_address,
        nft_type,
        symbol,
        nft_id,
        amount,
        first_acquired_ts,
        filename="reservoir.txt",
    )

    if (
        chain_name == "ETH"
        and entry["token"]["collection"]["floorAsk"]["source"]
        and entry["token"]["collection"]["floorAsk"]["source"]["name"] == "OpenSea"
        and entry["token"]["collection"]["floorAsk"]["price"]["currency"]["contract"]
        == ETH_NULL_ADDRESS
    ):
        eth_floor_rate = entry["token"]["collection"]["floorAsk"]["price"]["amount"]["decimal"]
        ct[contract_address]["eth_floor"] = eth_floor_rate

        log("Reservoir floor_rate", eth_floor_rate, filename="reservoir.txt")
