# -*- coding: utf-8 -*-
import os

from flask import Blueprint, render_template

from ..chain import Chain
from ..util import log

chains = Blueprint("chains", __name__)


@chains.route("/chains.html")
def chain_support():
    chains_support_info = []
    support_level_text_map = {10: "High", 5: "Medium", 3: "Low", 0: "None"}
    for chain_name in Chain.list(alphabetical=True):
        conf = Chain.CONFIG[chain_name]
        support_level = conf["support"]
        support_level_text = support_level_text_map[support_level]
        if support_level == 0:
            support_level_text = "Discontinued"

        data_source_url = "https://" + conf["scanner"]
        data_source_name = conf["scanner"]

        erc1155_support = 0
        if "1155_support" in conf:
            erc1155_support = conf["1155_support"]

        balance_token_support = "Available"
        if "debank_mapping" in conf and conf["debank_mapping"] is None:
            balance_token_support = "Not available"

        balance_nft_support = "Not available"
        if "simplehash_mapping" in conf:
            balance_nft_support = "Available"

        cp_availability = 3
        if "blockscout" in conf:
            cp_availability = 0
        if "cp_availability" in conf:
            cp_availability = conf["cp_availability"]

        if chain_name == "Solana":
            data_source_url = "https://www.quicknode.com/"
            data_source_name = "QuickNode RPC"
            balance_nft_support = "Available"

        chains_support_info.append(
            {
                "name": chain_name,
                "support_level": support_level,
                "support_level_text": support_level_text,
                "data_source_name": data_source_name,
                "data_source_url": data_source_url,
                "cp_availability": support_level_text_map[cp_availability],
                "erc1155_support": support_level_text_map[erc1155_support],
                "balance_token_support": balance_token_support,
                "balance_nft_support": balance_nft_support,
            }
        )
    log("chains_support_info", chains_support_info, filename="chain_support.txt")
    return render_template(
        "chains.html",
        title="Blockchain transactions to US tax form",
        chains=chains_support_info,
        version=os.environ.get("version"),
    )
