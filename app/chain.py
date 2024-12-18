# -*- coding: utf-8 -*-
import calendar
import math
import os
import random
import re
import time
import traceback
from collections import defaultdict
from datetime import datetime

import bs4
import requests

from .imports import Import
from .pool import Pools
from .transaction import Transaction, Transfer, normalize_address
from .util import clog, is_ethereum, log, log_error


class Chain:
    CONFIG = {
        # defaults:
        # scanner_name -> scanner without extension, or "blockscout" if blockscout:1
        # base asset -> name
        # coingecko_platform -> name
        # coingecko_id -> name
        # debank_mapping -> base asset
        "ETH": {
            "scanner": "etherscan.io",
            "api_key": "api_key_etherscan",
            "outbound_bridges": [
                "0XA0C68C638235EE32657E8F720A23CEC1BFC77C77",  # polygon
                "0X40EC5B33F54E0E8A33A975908C5BA1C14E5BBBDF",  # polygon
                "0x401f6c983ea34274ec46f84d70b31c151321188b",
                "0X59E55EC322F667015D7B6B4B63DC2DE6D4B541C3",  # bsc
                "0x1485e9852ac841b52ed44d573036429504f4f602",
                "0x4dbd4fc535ac27206064b68ffcf827b0a60bab3f",  # arbitrum
                "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # avalanche
                "0x09357819e5099232111d8377d5e089540e0b48bb",  # heco
            ],
            "inbound_bridges": [
                "0x8484ef722627bf18ca5ae6bcf031c23e6e922b30",
                "0XA0C68C638235EE32657E8F720A23CEC1BFC77C77",
                "0x40ec5b33f54e0e8a33a975908c5ba1c14e5bbbdf",
                "0xe78388b4ce79068e89bf8aa7f218ef6b9ab0e9d0",
                "0x09357819e5099232111d8377d5e089540e0b48bb",
            ],
            "wrapper": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
            "rate_limit": 10,
            "coingecko_platform": "ethereum",
            "coingecko_id": "ethereum",
            "simplehash_mapping": "ethereum",
            "covalent_mapping": "eth-mainnet",
            "dexscreener_mapping": "ethereum",
            "order": 0,
            "support": 10,
            "1155_support": 10,
            "cp_availability": 10,
            "routescan": 1,
        },
        "BSC": {
            "scanner": "bscscan.com",
            "base_asset": "BNB",
            "api_key": "api_key_bscscan",
            "outbound_bridges": ["0X2170ED0880AC9A755FD29B2688956BD959F933F8"],
            "inbound_bridges": ["0X8894E0A0C962CB723C1976A4421C95949BE2D4E3"],
            "wrapper": "0xbb4cdb9cbd36b01bd1cbaebf2de08d9173bc095c",
            "coingecko_platform": "binance-smart-chain",
            "coingecko_id": "binancecoin",
            "debank_mapping": "bsc",
            "simplehash_mapping": "bsc",
            "covalent_mapping": "bsc-mainnet",
            "order": 1,
            "support": 10,
            "cp_availability": 10,
        },
        "Arbitrum": {
            "scanner": "arbiscan.io",
            "base_asset": "ETH",
            "api_key": "api_key_arbiscan",
            "outbound_bridges": ["0x0000000000000000000000000000000000000064"],
            "inbound_bridges": ["0x000000000000000000000000000000000000006e"],
            "wrapper": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
            "coingecko_platform": "arbitrum-one",
            "coingecko_id": "ethereum",
            "debank_mapping": "arb",
            "simplehash_mapping": "arbitrum",
            "covalent_mapping": "arbitrum-mainnet",
            "order": 2,
            "support": 10,
            "1155_support": 5,
            "cp_availability": 5,
        },
        "Arbitrum Nova": {
            "scanner": "nova.arbiscan.io",
            "explorer_url": "https://api-nova.arbiscan.io/api",
            "base_asset": "ETH",
            "api_key": "api_key_arbiscan_nova",
            "wrapper": "0xf906A9c7b4d1207B38a2f18445047764763aB450",
            "coingecko_platform": "arbitrum-nova",
            "coingecko_id": "ethereum",
            "debank_mapping": "nova",
            "dexscreener_mapping": "arbitrumnova",
            "order": 3,
            "support": 3,
        },
        "Polygon": {
            "scanner": "polygonscan.com",
            "base_asset": "MATIC",
            "api_key": "api_key_polygonscan",
            "outbound_bridges": ["0X7CEB23FD6BC0ADD59E62AC25578270CFF1B9F619"],
            "inbound_bridges": ["0X0000000000000000000000000000000000000000"],
            "wrapper": "0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270",
            "coingecko_platform": "polygon-pos",
            "covalent_mapping": "matic-mainnet",
            "coingecko_id": "matic-network",
            "simplehash_mapping": "polygon",
            "order": 4,
            "support": 10,
            "1155_support": 3,
            "cp_availability": 10,
        },
        "zkEVM": {
            "scanner": "zkevm.polygonscan.com",
            "base_asset": "ETH",
            "api_key": "api_key_polygonscan_zkevm",
            "wrapper": "0x4F9A0e7FD2Bf6067db6994CF12E4495Df938E6e9",
            "coingecko_platform": "polygon-zkevm",
            "coingecko_id": "ethereum",
            "simplehash_mapping": "polygon-zkevm",
            "explorer_url": "https://api-zkevm.polygonscan.com/api",
            "order": 4.5,
            "support": 3,
            "1155_support": 3,
            "debank_mapping": None,
        },
        "Base": {
            "scanner": "basescan.org",
            "base_asset": "ETH",
            "api_key": "api_key_base",
            "wrapper": "0x4200000000000000000000000000000000000006",
            "coingecko_id": "ethereum",
            "simplehash_mapping": "base",
            "order": 4.6,
            "support": 3,
            "1155_support": 3,
            "debank_mapping": None,
            "routescan": 8453,
        },
        "Avalanche": {
            "scanner": "snowtrace.io",
            "base_asset": "AVAX",
            "api_key": "api_key_snowtrace",
            "outbound_bridges": ["0x49d5c2bdffac6ce2bfdb6640f4f80f226bc10bab"],
            "inbound_bridges": ["0x0000000000000000000000000000000000000000"],
            "wrapper": "0xb31f66aa3c1e785363f0875a1b74e27b85fd66c7",
            "coingecko_id": "avalanche-2",
            "simplehash_mapping": "avalanche",
            "order": 5,
            "support": 10,
            "1155_support": 5,
            "cp_availability": 5,
            "covalent_mapping": "avalanche-mainnet",
            "explorer_url": "https://api.routescan.io/v2/network/mainnet/evm/43114/api",
            "routescan": 43114,
        },
        "Optimism": {
            "scanner": "optimistic.etherscan.io",
            "base_asset": "ETH",
            "api_key": "api_key_etherscan_optimism",
            "wrapper": "0x4200000000000000000000000000000000000006",
            "coingecko_platform": "optimistic-ethereum",
            "coingecko_id": "ethereum",
            "debank_mapping": "op",
            "simplehash_mapping": "optimism",
            "explorer_url": "https://api-optimistic.etherscan.io/api",
            # 'covalent_mapping': 10, #covalent fees are also wrong
            "order": 6,
            "support": 5,
            "cp_availability": 3,
            "routescan": 10,
        },
        "Fantom": {
            "scanner": "ftmscan.com",
            "base_asset": "FTM",
            "api_key": "api_key_ftmscan",
            "wrapper": "0x21be370d5312f44cb42ce377bc9b8a0cef1a4c83",
            "covalent_mapping": "fantom-mainnet",
            "order": 7,
            "support": 10,
            "1155_support": 5,
            "cp_availability": 10,
        },
        "Cronos": {
            "scanner": "cronoscan.com",
            "base_asset": "CRO",
            "api_key": "api_key_cronoscan",
            "wrapper": "0x5C7F8A570d578ED84E63fdFA7b1eE72dEae1AE23",
            "coingecko_id": "crypto-com-chain",
            "order": 8,
            "support": 5,
            "cp_availability": 5,
        },
        "Solana": {
            "scanner": "solscan.io",
            "order": 9,
            "support": 10,
            "cp_availability": 5,
            "base_asset": "SOL",
            "coingecko_id": "solana",
        },  # special handling
        "Kava": {
            "scanner": "explorer.kava.io",
            "wrapper": "0xc86c7c0efbd6a49b35e8714c5f59d99de09a225b",
            "blockscout": 1,
            "order": 10,
            "support": 3,
        },
        "Celo": {
            "scanner": "celoscan.io",
            "base_asset": "CELO",
            "api_key": "api_key_celoscan",
            "wrapper": "0xc579D1f3CF86749E05CD06f7ADe17856c2CE3126",
            "order": 11,
            "support": 3,
        },
        "Moonbeam": {
            "scanner": "moonscan.io",
            "explorer_url": "https://api-moonbeam.moonscan.io/api",
            "base_asset": "GLMR",
            "api_key": "api_key_moonscan",
            "wrapper": "0xacc15dc74880c9944775448304b263d191c6077f",
            "debank_mapping": "mobm",
            "order": 10,
            "support": 3,
        },
        # 'Canto': {
        #     'scanner': 'evm.explorer.canto.io',
        #     'wrapper': '0x826551890dc65655a0aceca109ab11abdbd7a07b',
        #     'blockscout':1,
        #     'order': 10,
        #     'support': 3
        # },
        "Canto": {
            # 'scanner': 'tuber.build',
            "scanner": "explorer.plexnode.wtf",
            "wrapper": "0x826551890dc65655a0aceca109ab11abdbd7a07b",
            "blockscout": 1,
            "order": 10,
            "support": 3,
        },
        "Aurora": {
            "scanner": "explorer.mainnet.aurora.dev",
            "base_asset": "ETH",
            "debank_mapping": "aurora",
            "blockscout": 1,
            "order": 10,
            "support": 3,
            "cp_availability": 3,
        },
        "HECO": {
            "scanner": "hecoinfo.com",
            "base_asset": "HT",
            "api_key": "api_key_hecoinfo",
            "wrapper": "0x5545153ccfca01fbd7dd11c0b23ba694d9509a6f",
            "inbound_bridges": ["0xd8e32fbfb7da70237c130a6d8d6e12471f6d029d"],
            "outbound_bridges": ["0xd8e32fbfb7da70237c130a6d8d6e12471f6d029d"],
            "coingecko_platform": "huobi-token",
            "coingecko_id": "huobi-token",
            "debank_mapping": "heco",
            "order": 15,
            "support": 0,
            "cp_availability": 5,
        },
        # 'Gnosis': {
        #     'scanner': 'blockscout.com',
        #     'explorer_url':'https://blockscout.com/xdai/mainnet/api',
        #     'base_asset': 'XDAI',
        #     'api_key': '0bc0f6b7-c826-49f2-9959-749ffe4da4e8',
        #     'coingecko_platform': 'xdai',
        #     'coingecko_id': 'xdai',
        #     'simplehash_mapping':'gnosis',
        #     'blockscout': 1,
        #     'order': 15
        # },
        "Gnosis": {
            "scanner": "gnosisscan.io",
            "base_asset": "XDAI",
            "api_key": "api_key_gnosisscan",
            "wrapper": "0xe91d153e0b41518a2ce8dd3d7944fa863463a97d",
            "coingecko_platform": "xdai",
            "coingecko_id": "xdai",
            "simplehash_mapping": "gnosis",
            "dexscreener_mapping": "gnosischain",
            "order": 16,
            "support": 3,
            "1155_support": 3,
        },
        "KCC": {
            "scanner": "scan.kcc.io",
            "base_asset": "KCS",
            "coingecko_platform": "kucoin-community-chain",
            "coingecko_id": "kucoin-shares",
            "debank_mapping": "kcc",
            "blockscout": 1,
            "order": 17,
            "support": 3,
        },
        "Moonriver": {
            "scanner": "moonriver.moonscan.io",
            "scanner_name": "Moonscan",
            "explorer_url": "https://api-moonriver.moonscan.io/api",
            "base_asset": "MOVR",
            "api_key": "api_key_moonscan_moonriver",
            "wrapper": "0x98878b06940ae243284ca214f92bb71a2b032b8a",
            "order": 18,
            "support": 3,
        },
        # 'Metis': {
        #     'scanner': 'andromeda-explorer.metis.io',
        #     'wrapper': '0x75cb093e4d61d2a2e65d8e0bbb01de8d89b53481',
        #     'coingecko_platform': 'metis-andromeda',
        #     'coingecko_id': 'metis-token',
        #     'blockscout': 1,
        #     'order': 19,
        #     'support': 0,
        # },
        "Metis": {
            "scanner": "explorer.metis.io",
            "explorer_url": "https://api.routescan.io/v2/network/mainnet/evm/1/etherscan/api",
            "wrapper": "0x75cb093e4d61d2a2e65d8e0bbb01de8d89b53481",
            "coingecko_platform": "metis-andromeda",
            "coingecko_id": "metis-token",
            "order": 19,
            "support": 3,
            "routescan": 1088,
        },
        "Oasis": {
            "scanner": "explorer.emerald.oasis.dev",
            "base_asset": "ROSE",
            "wrapper": "0x21c718c22d52d0f3a789b752d4c2fd5908a8a733",
            "coingecko_id": "oasis-network",
            "dexscreener_mapping": "oasisemerald",
            "debank_mapping": None,
            "blockscout": 1,
            "order": 20,
            "support": 3,
        },
        "Songbird": {
            "scanner": "songbird-explorer.flare.network",
            "base_asset": "SGB",
            "wrapper": "0x02f0826ef6ad107cfc861152b32b52fd11bab9ed",
            "dexscreener_mapping": None,
            "blockscout": 1,
            "order": 21,
            "support": 3,
            "routescan": 19,
        },
        "Flare": {
            "scanner": "flare-explorer.flare.network",
            "base_asset": "FLR",
            "wrapper": "0x1D80c49BbBCd1C0911346656B529DF9E5c2F783d",
            "coingecko_id": "flare-networks",
            "coingecko_platform": "flare-network",
            "debank_mapping": None,
            "blockscout": 1,
            "order": 22,
            "support": 3,
            "routescan": 14,
        },
        "Step": {
            "scanner": "stepscan.io",
            "scanner_name": "Stepscan",
            "base_asset": "FITFI",
            "wrapper": "0xb58a9d5920af6ac1a9522b0b10f55df16686d1b6",
            "coingecko_platform": "step-network",
            "coingecko_id": "step-app-fitfi",
            "debank_mapping": "step",
            "dexscreener_mapping": "stepnetwork",
            "blockscout": 1,
            "order": 23,
            "support": 3,
            "routescan": 1234,
        },
        "Doge": {
            "scanner": "explorer.dogechain.dog",
            "wrapper": "0xb7ddc6414bf4f5515b52d8bdd69973ae205ff101",
            "coingecko_platform": "dogechain",
            "coingecko_id": "dogecoin",
            "dexscreener_mapping": "dogechain",
            "blockscout": 1,
            "order": 24,
            "support": 3,
        },
        "Velas": {
            "scanner": "evmexplorer.velas.com",
            "base_asset": "VLX",
            "wrapper": "0xb58a9d5920af6ac1a9522b0b10f55df16686d1b6",
            "debank_mapping": None,
            "blockscout": 1,
            "order": 25,
            "support": 3,
        },
        # 'Boba': {
        #     'scanner': 'blockexplorer.bobabeam.boba.network',
        #     'wrapper': '0xdeaddeaddeaddeaddeaddeaddeaddeaddead0000',
        #     'coingecko_id': 'boba-network',
        #     'blockscout': 1,
        #     'order': 26,
        #     'support': 3
        # },
        "Boba": {
            "scanner": "bobascan.com",
            "scanner_name": "Bobascan",
            "api_key": "api_key_bobascan",
            "wrapper": "0xdeaddeaddeaddeaddeaddeaddeaddeaddead0000",
            "order": 26,
            "support": 0,
        },
        "SXnetwork": {
            "scanner": "explorer.sx.technology",
            "wrapper": "0xaa99bE3356a11eE92c3f099BD7a038399633566f",
            "coingecko_platform": "sx-network",
            "coingecko_id": "sx-network",
            "debank_mapping": None,
            "blockscout": 1,
            "order": 27,
            "support": 3,
        },
        "smartBCH": {
            "scanner": "sonar.cash",
            "scanner_name": "SonarCash",
            "base_asset": "BCH",
            "wrapper": "0x3743ec0673453e5009310c727ba4eaf7b3a1cc04",
            "coingecko_id": "bitcoin-cash",
            "debank_mapping": "sbch",
            "blockscout": 1,
            "order": 28,
            "support": 0,
        },
        "EVMOS": {
            "scanner": "blockscout.evmos.org",
            "wrapper": "0xd4949664cd82660aae99bedc034a0dea8a0bd517",
            "blockscout": 1,
            "order": 29,
            "support": 0,
        },
        # 'Bitgert': {
        #     'scanner': 'brisescan.com',
        #     'scanner_name': 'Brisescan',
        #     'base_asset':'BRISE',
        #     'wrapper': '0x0eb9036cbe0f052386f36170c6b07ef0a0e3f710',
        #     'coingecko_id': 'bitrise-token',
        #     'blockscout': 1,
        #     'order': 28
        # },
        "ETC": {
            "scanner": "blockscout.com",
            "explorer_url": "https://blockscout.com/etc/mainnet/api",
            "base_asset": "ETC",
            "wrapper": "0x1953cab0E5bFa6D4a9BaD6E05fD46C1CC6527a5a",
            "coingecko_platform": "ethereum-classic",
            "coingecko_id": "ethereum-classic",
            "dexscreener_mapping": "ethereumclassic",
            "blockscout": 1,
            "order": 100,
            "support": 3,
        },
    }

    def __init__(
        self,
        name,
        domain,
        main_asset,
        api_key,
        outbound_bridges=(),
        inbound_bridges=(),
        wrapper=None,
        rate_limit=5,
        blockscout=False,
        explorer_url=None,
        is_upload=False,
        discontinued=False,
        routescan_id=None,
    ):
        self.is_upload = is_upload
        self.domain = domain
        self.explorer_url = None
        if domain is not None:
            if explorer_url is not None:
                self.explorer_url = explorer_url
            else:
                if blockscout:
                    self.explorer_url = "https://" + domain + "/api"
                else:
                    self.explorer_url = "https://api." + domain + "/api"

        self.blockscout = blockscout
        self.main_asset = main_asset
        self.api_key = api_key
        self.name = name
        self.outbound_bridges = []
        self.inbound_bridges = []
        for bridge in outbound_bridges:
            self.outbound_bridges.append(normalize_address(bridge))

        for bridge in inbound_bridges:
            self.inbound_bridges.append(normalize_address(bridge))
        self.wrapper = None
        if wrapper is not None:
            self.wrapper = normalize_address(wrapper)

        self.hif = (
            "47M65BG4riNsp4HwtEYdKx9dy4rC6QNM8zY1h1jf3aXE"
            "oWmGgDcrZcFLj7777ebvfHsThoTzVWZkpo6kLPuB9NSD"
        )

        self.wait_time = 1 / float(rate_limit) + 0.05

        self.wait_time *= 2

        self.entity_map = {}
        self.addresses_initialized = False

        self.pools = Pools(self)
        self.progress_bar = None

        self.decimal_info = {}

        self.transferred_tokens = set()

        self.proxy = "http://5uu5k:7sdcf2x2@104.128.115.239:5432"
        self.discontinued = discontinued

        self.routescan_id = routescan_id
        self.use_routescan_backup = False
        if self.explorer_url is not None and "routescan.io" in self.explorer_url:
            self.use_routescan_backup = True
        self.current_import = None

    def __str__(self):
        return self.name + " chain"

    def __repr__(self):
        return self.__str__()

    @classmethod
    def list(cls, alphabetical=False):
        dict_items = list(Chain.CONFIG.items())
        if alphabetical:
            dict_list = sorted(dict_items, key=lambda item: item[0].lower())
        else:
            dict_list = sorted(dict_items, key=lambda item: item[1]["order"])
        name_list = []
        for entry in dict_list:
            name_list.append(entry[0])
        return name_list

    @classmethod
    def config_json(cls):
        dump = {}
        for chain_name in Chain.list():
            conf = Chain.CONFIG[chain_name]
            debank = 1
            if "debank_mapping" in conf and conf["debank_mapping"] is None:
                debank = 0
            scanner = conf["scanner"]
            dump[chain_name] = {"scanner": scanner, "debank": debank}
        return dump

        # scanner:'etherscan.io', base_token:'ETH', scanner_name:'Etherscan', debank:1

    @classmethod
    def from_upload(cls, upload_source):
        chain = Chain(upload_source, None, None, None, is_upload=True)
        return chain

    @classmethod
    def from_name(cls, chain_name):
        conf = Chain.CONFIG[chain_name]
        base_asset = chain_name
        if "base_asset" in conf:
            base_asset = conf["base_asset"]

        api_key = None
        if "api_key" in conf:
            api_key = os.environ.get(conf["api_key"])
        outbound_bridges = ()
        inbound_bridges = ()
        wrapper = None
        rate_limit = 5
        blockscout = False
        explorer_url = None

        if "outbound_bridges" in conf:
            outbound_bridges = conf["outbound_bridges"]

        if "inbound_bridges" in conf:
            inbound_bridges = conf["inbound_bridges"]

        if "wrapper" in conf:
            wrapper = conf["wrapper"]

        if "rate_limit" in conf:
            rate_limit = conf["rate_limit"]

        if "blockscout" in conf:
            blockscout = conf["blockscout"]

        if "explorer_url" in conf:
            explorer_url = conf["explorer_url"]

        discontinued = False
        if "support" in conf and conf["support"] == 0:
            discontinued = True

        routescan_id = None
        if "routescan" in conf:
            routescan_id = conf["routescan"]

        chain = Chain(
            chain_name,
            conf["scanner"],
            base_asset,
            api_key,
            outbound_bridges=outbound_bridges,
            inbound_bridges=inbound_bridges,
            wrapper=wrapper,
            blockscout=blockscout,
            explorer_url=explorer_url,
            rate_limit=rate_limit,
            discontinued=discontinued,
            routescan_id=routescan_id,
        )
        return chain

    def update_pb(self, entry=None, percent=None):
        if self.progress_bar:
            if entry is not None:
                entry = self.name + ": " + entry
            self.progress_bar.update(entry, percent)

    def init_addresses(self, address_db, contract_list=None):
        log("init_addresses", self.name, filename="address_lookups.txt")
        t = time.time()
        if self.addresses_initialized or self.blockscout:
            return

        try:
            if contract_list is None:
                rows = address_db.select(
                    "SELECT address, ancestor_address, trim(entity) FROM "
                    + self.name.upper().replace(" ", "_")
                    + "_addresses"
                )
                t1 = time.time()
                log("init addresses timing 1", self.name, t1 - t, filename="address_lookups.txt")
                for row in rows:
                    self.entity_map[row[0]] = row[2], row[1]
                log(
                    "init addresses timing 2",
                    self.name,
                    time.time() - t1,
                    filename="address_lookups.txt",
                )
            else:
                for address in contract_list:
                    rows = address_db.select(
                        "SELECT address, ancestor_address, trim(entity) FROM "
                        + self.name.upper().replace(" ", "_")
                        + "_addresses WHERE address='"
                        + address
                        + "' OR ancestor_address='"
                        + address
                        + "'"
                    )
                    for row in rows:
                        self.entity_map[row[0]] = row[2], row[1]
                log(
                    "init addresses timing 3",
                    self.name,
                    time.time() - t,
                    filename="address_lookups.txt",
                )
        except:
            log_error("No addresses found")
        self.addresses_initialized = True

    def unwrap(self, what):
        if what == self.wrapper:
            return self.main_asset
        return what

    def get_progenitor_entity(self, address):
        if address in self.entity_map:
            return self.entity_map[address]
        return None, None

    def get_all_transaction_from_api(
        self,
        address,
        action,
        reps=3,
        offset=None,
        max_pages=5,
        max_per_page=10000,
        timeout=30,
        page=None,
        sort="asc",
        startblock=0,
    ):

        done = False
        # errors = set()
        all_data = []
        tr_uids = set()
        cur_rep = 0
        page_idx = 0

        if startblock is not None:
            sb = str(startblock)

        headers = {}
        if self.name in ["Moonriver", "Moonbeam"]:  # ,'Arbitrum','Optimism']:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36"
                ),
                "cache-control": "max-age=0",
                "accept-language": "en-US,en;q=0.9,ru;q=0.8",
                "upgrade-insecure-requests": "1",
                "accept": (
                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
                ),
            }
        while not done:
            overlap_cnt = 0
            self.update_pb()
            if self.use_routescan_backup:
                explorer_url = (
                    f"https://api.routescan.io/v2/network/mainnet/evm/"
                    f"{self.routescan_id}/etherscan/api"
                )
                offset = 10000
            else:
                explorer_url = self.explorer_url

            url = explorer_url + "?module=account&action=" + action + "&address=" + address
            if startblock is not None:
                url += "&startblock=" + sb
                if self.name == "HECO":
                    url += "&endblock=1000000000"
            if self.api_key is not None:
                url += "&apikey=" + self.api_key
            if offset is not None:
                url += "&offset=" + str(offset)
            if page is not None:
                url += "&page=" + str(page)
            if sort is not None:
                url += "&sort=" + str(sort)
            log("URL", url)
            resp = None
            try:
                resp = requests.get(url, headers=headers, timeout=timeout)
            except:
                if self.routescan_id is not None and self.use_routescan_backup is False:
                    self.use_routescan_backup = True
                    return self.get_all_transaction_from_api(
                        address,
                        action,
                        reps=reps - 1,
                        offset=offset,
                        max_pages=max_pages,
                        max_per_page=max_per_page,
                        timeout=timeout,
                        page=page,
                        sort=sort,
                        startblock=startblock,
                    )

                time.sleep(3)
                cur_rep += 1
                if cur_rep == reps:
                    self.current_import.add_error(
                        Import.NO_API_RESPONSE, chain=self, address=address, txtype=action
                    )
                    log_error(
                        "Failed to get transactions after " + str(reps) + " tries",
                        url,
                        "exception",
                        action,
                        address,
                        self.name,
                    )
                    break
                continue

            try:
                res = resp.json()
                if (
                    "status" in res
                    and res["status"] in [0, "0"]
                    and "message" in res
                    and res["message"]
                    not in [
                        "No transactions found",
                        "No internal transactions found",
                        "No token transfers found",
                    ]
                ):
                    if action != "token1155tx":
                        self.current_import.add_error(
                            Import.NOTHING_RETURNED,
                            chain=self,
                            address=address,
                            txtype=action,
                            debug_info=res["message"],
                        )
                        log_error(
                            "Failed to get transactions, bad status",
                            url,
                            action,
                            address,
                            self.name,
                            res,
                        )
                    break
                data = res["result"]
            except:
                time.sleep(3)
                cur_rep += 1
                if cur_rep == reps:
                    self.current_import.add_error(
                        Import.BAD_API_RESPONSE, chain=self, address=address, txtype=action
                    )
                    log_error(
                        "Failed to get transactions after " + str(reps) + " tries",
                        url,
                        "exception",
                        action,
                        address,
                        self.name,
                        "last response",
                        resp.status_code,
                        resp.content,
                    )
                    break
                continue

            if not isinstance(data, list):
                data = []
            cur_rep = 0
            for entry in data:
                entry["confirmations"] = (
                    1  # overwrite this because it changes between paginated API requests,
                    # causing the same entry to be recorded twice
                )
                uid = str(entry)
                try:
                    if (
                        uid not in tr_uids or entry["blockNumber"] != sb
                    ):  # possible duplicates on rollover of a block
                        all_data.append(entry)
                except:
                    self.current_import.add_error(
                        Import.UNEXPECTED_DATA, chain=self, address=address, txtype=action
                    )
                    log_error("Unexpected data from scanner", url, action, address, self.name, data)
                    break
                if uid not in tr_uids:
                    tr_uids.add(uid)
                else:
                    overlap_cnt += 1
            page_idx += 1
            if len(data) < max_per_page or page_idx == max_pages or overlap_cnt > max_per_page // 2:
                done = True
                if len(all_data) >= max_per_page * 5 - 200:
                    self.current_import.add_error(
                        Import.TOO_MANY_TRANSACTIONS, chain=self, address=address, txtype=action
                    )

            else:
                sb = data[-1]["blockNumber"]
            time.sleep(1)

        return all_data

    def check_validity(self, address):
        if self.name == "Solana":
            if address[0] == "0" and address[1] == "x":
                return False
            if len(address) < 32 or len(address) > 44:
                return False
            return True
        if address[0] != "0" or address[1] != "x" or len(address) != 42:
            return False
        return True

    def check_presence(self, address):
        if self.discontinued:
            return False
        if self.name == "EVMOS":
            data = self.get_all_transaction_from_api(
                address, "txlist", reps=1, max_pages=1, timeout=5, sort=None, startblock=None
            )
        else:
            data = self.get_all_transaction_from_api(
                address, "txlist", page=1, offset=100, reps=1, max_pages=1, timeout=30
            )
        for entry in data:
            fr = normalize_address(entry["from"])
            to = normalize_address(entry["to"])
            if address in (fr, to):
                return True
        return False

    def get_transactions(self, user, address, pb_alloc):
        if self.discontinued:
            return {}
        mpp = 10000
        if self.name == "HECO":
            mpp = 1000

        rq_cnt = 2
        if not self.blockscout:
            rq_cnt += 1
        if self.name in [
            "ETH",
            "Polygon",
            "Arbitrum",
            "Optimism",
            "Avalanche",
            "Gnosis",
            "zkEVM",
            "Base",
        ]:
            rq_cnt += 1
        if self.name == "Polygon":
            rq_cnt += 1
        per_type_alloc = pb_alloc / float(rq_cnt)

        hif = self.hif

        self.update_pb("Retrieving " + self.main_asset + " transactions for " + address, 0)
        div = 1000000000000000000.0
        log("\n\ngetting transactions for", address, self.name)

        # because shitty heco chain doesn't have hashes on txlistinternal,
        # we need to try to locate tx by block
        if self.name == "HECO":
            blockmap = defaultdict(list)

        data = self.get_all_transaction_from_api(address, "txlist", max_per_page=mpp)

        base_vals = defaultdict(
            list
        )  # sometimes internal transactions on Fantom duplicate base transactions

        transactions = {}
        for entry in data:
            hash = entry["hash"]
            if hash == hif:
                log("FROM API-base", entry)
            ts = entry["timeStamp"]
            nonce = entry["nonce"]
            block = entry["blockNumber"]
            if hash not in transactions:
                transactions[hash] = Transaction(user, self)

            T = transactions[hash]
            if self.name == "HECO":
                blockmap[block].append(hash)
            fr = entry["from"].lower()
            to = entry["to"].lower()
            input = entry["input"]
            if input == "deprecated":
                input_len = -1
                input = None
            else:
                input_len = len(input)
                if normalize_address(fr) == normalize_address(address) and input_len > 2:
                    T.interacted = normalize_address(to)
                    T.originator = normalize_address(fr)
                    if "functionName" in entry and len(entry["functionName"]):
                        function = entry["functionName"]
                        args = function.find("(")
                        if args != -1:
                            function = function[:args]
                        T.function = function
                    elif "methodId" in entry and len(entry["methodId"]) == 10:
                        T.function = entry["methodId"]
                    elif len(input) >= 10:
                        T.function = input[:10]

            val = float(entry["value"]) / div

            if input_len > 0:
                base_vals[hash].append(val)
            fee = float(entry["gasUsed"]) * float(entry["gasPrice"]) / div

            if self.name == "Fantom":  # inconsistent data from scanner, corrected w/covalent
                T.success = True
            else:
                if entry["isError"] == "1":
                    val = 0

                receipt_status = entry["txreceipt_status"]
                if receipt_status == "1":  # or entry['isError'] != '1':
                    T.success = True
                else:
                    T.success = False

            row = [
                hash,
                ts,
                nonce,
                block,
                fr,
                to,
                val,
                self.main_asset,
                self.main_asset,
                None,
                None,
                fee,
                input_len,
                input,
            ]
            T.append(Transfer.BASE, row)

        self.update_pb("Retrieving internal transactions for " + address, per_type_alloc)
        data = self.get_all_transaction_from_api(address, "txlistinternal", max_per_page=mpp)
        for entry in data:
            # print(entry)

            ts = entry["timeStamp"]
            block = entry["blockNumber"]
            type = entry["type"]
            if type == "delegatecall":
                continue

            if self.name != "HECO":
                if self.blockscout:
                    hash = entry["transactionHash"]
                else:
                    hash = entry["hash"]
                if hash == hif:
                    log("FROM API-internal", entry)
            else:
                if len(blockmap[block]) == 1:
                    hash = blockmap[block][0]
                else:
                    continue

            if hash not in transactions:
                transactions[hash] = Transaction(user, self)
            fr = entry["from"].lower()
            to = entry["to"].lower()
            input = entry["input"]
            if input == "deprecated":
                input_len = -1
                input = None
            else:
                input_len = len(input)
            val = float(entry["value"]) / div

            if transactions[hash].success is False or (
                transactions[hash].success is None and entry["isError"] == "1"
            ):
                val = 0

            row = [
                hash,
                ts,
                None,
                block,
                fr,
                to,
                val,
                self.main_asset,
                self.main_asset,
                None,
                None,
                0,
                input_len,
                input,
            ]
            # if val > 0:
            if self.name == "Fantom" and val in base_vals[hash]:
                continue  # skip Fantom duplicate

            transactions[hash].append(Transfer.INTERNAL, row)

        self.update_pb("Retrieving token transactions for " + address, per_type_alloc)
        data = self.get_all_transaction_from_api(address, "tokentx", max_per_page=mpp)
        for entry in data:
            hash = entry["hash"]
            if hash == hif:
                log("FROM API-tokens", entry)
            ts = entry["timeStamp"]

            fr = entry["from"].lower()
            to = entry["to"].lower()
            input = entry["input"]
            if input == "deprecated":
                input_len = -1
                input = None
            else:
                input_len = len(input)
            token_contract = entry["contractAddress"].lower()
            nonce = entry["nonce"]
            block = entry["blockNumber"]
            type = Transfer.ERC20

            # blockscout sticks NFT transactions together with tokens
            if self.blockscout and "tokenID" in entry:
                token_nft_id = str(entry["tokenID"])
                val = 1
                token = entry["tokenSymbol"]
            else:
                token_nft_id = None
                try:
                    decimals = int(entry["tokenDecimal"])
                    token = entry["tokenSymbol"]
                except:
                    # very rarely missing info
                    val = entry["value"]
                    if len(val) < 18:
                        decimals = 6
                    else:
                        decimals = 18
                    token = "Unknown token"

                tokendiv = float(math.pow(10, decimals))
                self.decimal_info[token_contract] = tokendiv

                val = float(entry["value"]) / tokendiv

            if hash not in transactions:
                transactions[hash] = Transaction(user, self)
            if (
                self.name == "Optimism"
                and token_contract == "0xdeaddeaddeaddeaddeaddeaddeaddeaddead0000"
            ):  # Optimism L1->L2 deposit
                token = token_contract = "ETH"
                type = Transfer.BASE

            # Celo native asset interchangeable
            if (
                self.name == "Celo"
                and token_contract == "0x471ece3750da237f93b8e339c536989b8978a438"
            ):
                type = Transfer.BASE
                token = token_contract = "CELO"

            if (
                self.name == "Metis"
                and token_contract == "0xdeaddeaddeaddeaddeaddeaddeaddeaddead0000"
            ):
                type = Transfer.BASE
                token = token_contract = "METIS"

            if transactions[hash].success is False:
                val = 0

            row = [
                hash,
                ts,
                nonce,
                block,
                fr,
                to,
                val,
                token,
                token_contract,
                None,
                token_nft_id,
                0,
                input_len,
                input,
            ]
            transactions[hash].append(type, row)

        if not self.blockscout:
            self.update_pb("Retrieving NFT transactions for " + address, per_type_alloc)
            data = self.get_all_transaction_from_api(address, "tokennfttx", max_per_page=mpp)
            for entry in data:
                hash = entry["hash"]
                if hash == hif:
                    log("FROM API-nfts", entry)
                ts = entry["timeStamp"]

                fr = entry["from"].lower()
                to = entry["to"].lower()
                input = entry["input"]
                if input == "deprecated":
                    input_len = -1
                    input = None
                else:
                    input_len = len(input)
                token_contract = entry["contractAddress"].lower()
                token = entry["tokenSymbol"]  # + " ("+entry['tokenID']+")"
                token_nft_id = entry["tokenID"]
                val = 1
                fee = 0  # accounted in base transactions
                nonce = entry["nonce"]
                block = entry["blockNumber"]
                if hash not in transactions:
                    transactions[hash] = Transaction(user, self)
                row = [
                    hash,
                    ts,
                    nonce,
                    block,
                    fr,
                    to,
                    val,
                    token,
                    token_contract,
                    None,
                    str(token_nft_id),
                    0,
                    input_len,
                    input,
                ]
                transactions[hash].append(4, row)

        if self.name in [
            "ETH",
            "Polygon",
            "Arbitrum",
            "Optimism",
            "Avalanche",
            "Gnosis",
            "zkEVM",
            "Base",
        ]:
            self.update_pb("Retrieving ERC1155 transactions for " + address, per_type_alloc)
            data = self.get_all_transaction_from_api(address, "token1155tx", max_per_page=mpp)
            log("erc1155 transfer count on", self.name, len(data), filename="aux_log.txt")
            for entry in data:
                hash = entry["hash"]
                # log('erc1155 transfer on',self.name,hash, entry,filename='aux_log.txt')
                if hash == hif:
                    log("FROM API-1155", entry)
                ts = entry["timeStamp"]

                fr = entry["from"].lower()
                to = entry["to"].lower()
                input_len = -1
                input = None
                token_contract = entry["contractAddress"].lower()
                token = entry["tokenSymbol"]
                if token == "":
                    token = "ERC1155"  # matches what was scraped in scrape_erc1155 for symbols
                token_nft_id = entry["tokenID"]
                try:
                    val = float(entry["tokenValue"])
                except:
                    val = 1
                nonce = entry["nonce"]
                block = entry["blockNumber"]
                if hash not in transactions:
                    transactions[hash] = Transaction(user, self)
                row = [
                    hash,
                    ts,
                    nonce,
                    block,
                    fr,
                    to,
                    val,
                    token,
                    token_contract,
                    None,
                    str(token_nft_id),
                    0,
                    input_len,
                    input,
                ]
                transactions[hash].append(5, row)

        if self.name == "Polygon":
            self.update_pb(
                "Page-scraping plasma deposit transactions for " + address, per_type_alloc
            )
            self.scrape_plasma(user, address, transactions)

        return transactions

    # corrects scanners' deficiencies
    def correct_transactions(self, address, transactions, pb_alloc):
        # pb_alloc = 5. / self.chain_count

        self.update_pb("Correcting transactions for " + address, 0)
        running_amounts = defaultdict(float)
        max_amounts = defaultdict(float)
        for idx, transaction in enumerate(transactions.values()):
            total_fee = 0
            wrap = False
            in_cnt = 0
            out_cnt = 0
            hash, ts, nonce, block = transaction.grouping[0][1][0:4]
            tx_symbols = {}
            tx_amounts = defaultdict(float)

            for _, (type, sub_data, _, _, _, _, _, _) in enumerate(transaction.grouping):
                (
                    hash,
                    ts,
                    nonce,
                    block,
                    fr,
                    to,
                    val,
                    token,
                    token_contract,
                    _coingecko_id,
                    token_nft_id,
                    base_fee,
                    _input_len,
                    input,
                ) = sub_data
                clog(transaction, "correcting, fee?", base_fee, fr, address)
                if val != 0:
                    token_contract_mod = token_contract
                    if token_nft_id is not None:
                        token_contract_mod = token_contract + "_" + token_nft_id
                    tx_symbols[token_contract_mod] = token

                    if fr == address:
                        out_cnt += 1
                        tx_amounts[token_contract_mod] -= val
                        running_amounts[token_contract_mod] -= val

                    if to == address:
                        in_cnt += 1
                        tx_amounts[token_contract_mod] += val
                        running_amounts[token_contract_mod] += val
                        if running_amounts[token_contract_mod] > max_amounts[token_contract_mod]:
                            max_amounts[token_contract_mod] = running_amounts[token_contract_mod]

                    if input is not None and self.wrapper in (to, fr):
                        wrap = True

                if fr == address:
                    total_fee += base_fee

            if self.hif == transaction.hash:
                log("tx_amounts", tx_amounts, out_cnt, in_cnt, filename="specific_tx.txt")
                for token_contract_mod, amount in tx_amounts.items():
                    log(
                        "running_amount",
                        token_contract_mod,
                        running_amounts[token_contract_mod],
                        filename="specific_tx.txt",
                    )

            # wrap/unwrap missing a transfer?
            if wrap and self.name != "Fantom" and not self.blockscout:
                if (
                    self.name == "Arbitrum"
                ):  # remove duplicate internal transfer on wrap, but not on unwrap
                    new_grouping = []
                    for row in transaction.grouping:
                        if row[0] != 2 or row[1][5] == address:
                            new_grouping.append(row)
                    transaction.grouping = new_grouping
                else:
                    contract, amount = list(tx_amounts.items())[0]
                    if contract == self.main_asset:
                        wrap_token = self.wrapper
                        wrap_symbol = "W" + self.main_asset
                        wrap_type = 3
                    else:
                        wrap_token = wrap_symbol = self.main_asset
                        wrap_type = 1
                    if in_cnt == 1:
                        wrap_fr = address
                        wrap_to = self.wrapper
                    else:
                        wrap_fr = self.wrapper
                        wrap_to = address
                    running_amounts[wrap_token] -= amount
                    row = [
                        hash,
                        ts,
                        nonce,
                        block,
                        wrap_fr,
                        wrap_to,
                        abs(amount),
                        wrap_symbol,
                        wrap_token,
                        None,
                        None,
                        0,
                        0,
                        None,
                    ]
                    transaction.append(wrap_type, row, synthetic=Transfer.WRAP)

            # network fee
            if total_fee > 0:
                clog(transaction, "Adding fee", total_fee)
                row = [
                    hash,
                    ts,
                    nonce,
                    block,
                    address,
                    "network",
                    total_fee,
                    self.main_asset,
                    self.main_asset,
                    None,
                    None,
                    0,
                    0,
                    None,
                ]
                transaction.append(1, row, synthetic=Transfer.FEE)

            if self.name == "Polygon":
                if len(transaction.grouping) > 1:
                    # 0x0000000000000000000000000000000000001010 is Matic, and is duplicated
                    if (
                        "0x0000000000000000000000000000000000001010" in tx_amounts
                        and "MATIC" in tx_amounts
                    ):
                        if (
                            tx_amounts["0x0000000000000000000000000000000000001010"]
                            == tx_amounts["MATIC"]
                        ):
                            new_grouping = []
                            for idx, entry in enumerate(transaction.grouping):
                                type, sub_data, _, _, _, _, _, _ = entry
                                if (
                                    type == 3
                                    and sub_data[8] == "0x0000000000000000000000000000000000001010"
                                ):
                                    entry[0] = 1
                                    entry[1][8] = "MATIC"
                                    new_grouping.append(entry)
                                elif (
                                    type in [1, 2]
                                    and sub_data[8] == "MATIC"
                                    and sub_data[5] != "network"
                                ):
                                    continue
                                else:
                                    new_grouping.append(entry)
                            transaction.grouping = new_grouping

            if self.name == "Arbitrum":
                # bridging into arbitrum has screwed up direction
                if len(transaction.grouping) == 1:
                    type, sub_data, _, _, _, _, _, _ = transaction.grouping[0]
                    (
                        hash,
                        ts,
                        nonce,
                        block,
                        fr,
                        to,
                        val,
                        token,
                        token_contract,
                        _coingecko_id,
                        token_nft_id,
                        base_fee,
                        _input_len,
                        input,
                    ) = sub_data
                    if (
                        to == "0x000000000000000000000000000000000000006e"
                        and input[:10] == "0x679b6ded"
                    ):
                        row = sub_data
                        row[4] = to
                        row[5] = fr
                        transaction.grouping = [
                            [1, row, None, None, None, None, Transfer.ARBITRUM_BRIDGE, None]
                        ]

                # in rare case arbitrum duplicates ETH transfer,
                # ex 0xdd9c3074593fc1a40e0cd3ec18d98990fc481b7848d42819565a431bceac34c5
                eth_transfer_hashes = []
                to_delete = []
                for idx, entry in enumerate(transaction.grouping):
                    type, sub_data, _, _, _, _, _, _ = entry
                    if type in (1, 2):
                        (
                            hash,
                            ts,
                            nonce,
                            block,
                            fr,
                            to,
                            val,
                            token,
                            token_contract,
                            _coingecko_id,
                            token_nft_id,
                            base_fee,
                            _input_len,
                            input,
                        ) = sub_data
                        tr_hash = fr + "_" + to + "_" + str(val)
                        if tr_hash not in eth_transfer_hashes:
                            eth_transfer_hashes.append(tr_hash)
                        else:
                            to_delete.append(idx)
                if len(to_delete) > 0:
                    new_grouping = []
                    for idx, entry in enumerate(transaction.grouping):
                        if idx not in to_delete:
                            new_grouping.append(entry)
                    transaction.grouping = new_grouping

        self.update_pb("Correcting transactions for " + address, pb_alloc)

    def scrape_plasma(self, user, address, transactions):
        page = 1
        done = False
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36"
            ),
            "cache-control": "max-age=0",
            "accept-language": "en-US,en;q=0.9,ru;q=0.8",
            "upgrade-insecure-requests": "1",
            "accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
            ),
        }
        session = requests.session()
        session.proxies = {"http": self.proxy, "https": self.proxy}

        while not done:
            self.update_pb()
            url = "https://polygonscan.com/txnbridge?a=" + address + "&ps=100&p=" + str(page)
            time.sleep(random.randint(100, 400) / 1000.0)
            try:
                resp = session.get(url, headers=headers, timeout=5)
            except:
                log_error("Failed to scrape plasma deposits, timeout", address)
                return
            if resp.status_code != 200:
                log_error(
                    "Failed to scrape plasma deposits, status code",
                    resp.status_code,
                    "content",
                    resp.content,
                )
                return
            html = resp.content.decode("utf-8")
            if "There are no matching entries" in html:
                return
            soup = bs4.BeautifulSoup(html, features="html.parser")
            tb = soup.find("table", class_="table-hover")
            try:
                rows = tb.find_all("tr")
            except:
                log_error("Failed to scrape plasma deposits, content dump", resp.content)
                return

            if len(rows) == 1:
                break
            for row in rows[1:]:
                cells = row.find_all("td")
                try:
                    txhash_html = cells[0]
                    txhash = txhash_html.find("a").contents[0]

                    ts_html = cells[2]
                    ts = ts_html.find("span")["title"]
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")  # 2021-10-02 1:25:32
                    ts = calendar.timegm(dt.utctimetuple())

                    fr_html = cells[3]
                    fr_a = fr_html.find("a")
                    if fr_a:
                        fr = fr_a["href"][9:51]
                    else:
                        fr = fr_html.find("span")["title"]

                    to_html = cells[5]
                    to = to_html.find("span").contents[0]

                    amount = cells[6].contents[0].replace(",", "")

                    what_html = cells[7].find("a")
                    what = what_html["href"][7:49]
                    symbol = what_html.contents[-1]
                    match = re.search(r"\((.*?)\)", symbol)
                    symbol = match.group()[1:-1]
                    if symbol == "MATIC":
                        what = symbol
                        type = 1
                    else:
                        type = 3

                    if txhash not in transactions:
                        transactions[txhash] = Transaction(user, self)
                    row = [
                        txhash,
                        ts,
                        None,
                        None,
                        fr,
                        to,
                        float(amount),
                        symbol,
                        what,
                        None,
                        None,
                        0,
                        0,
                        None,
                    ]
                    if txhash == self.hif:
                        log(
                            "SCRAPED",
                            {
                                "hash": txhash,
                                "type": "plasma deposit",
                                "ts": ts,
                                "fr": fr,
                                "to": to,
                                "amount": amount,
                                "symbol": symbol,
                                "what": what,
                            },
                        )
                    transactions[txhash].append(type, row)
                except:
                    log_error("Failed to scrape plasma deposits", address, cells)
                    log("Failed to scrape plasma deposits", traceback.format_exc(), cells)
                    done = True
                    break

            if len(rows) != 101:
                done = True

            page += 1

    def covalent_download(self, chain_data, pb_alloc=None, max_requests=50):
        tstart = time.time()
        key = os.environ.get("api_key_covalenthq")  # premium
        addresses = chain_data["import_addresses"]

        try:
            chain_id = str(Chain.CONFIG[self.name]["covalent_mapping"])
        except:
            return

        log("covalent_download", self.name, addresses, filename="covalent.txt")

        session = requests.session()
        session.auth = (key, "")
        session.headers = {"Content-Type": "application/json"}

        covalent_dump = {}

        for address in addresses:
            ps = 1000
            if pb_alloc is not None:
                self.update_pb(
                    "Retrieving additional information from CovalentHQ for "
                    + address
                    + " (this might take up to 5 minutes)",
                    pb_alloc,
                )
            done = False
            page_num = 0
            idx = 0
            covalent_dump[address] = []
            while not done:
                idx += 1
                if pb_alloc is not None:
                    self.update_pb(
                        "Retrieving additional information from CovalentHQ for "
                        + address
                        + ", batch "
                        + str(idx)
                        + " (this might take up to 5 minutes)"
                    )

                url = (
                    "https://api.covalenthq.com/v1/"
                    + chain_id
                    + "/address/"
                    + address
                    + "/transactions_v2/?no-logs=true&page-size="
                    + str(ps)
                )
                if page_num != 0:
                    url += "&page-number=" + str(page_num)
                log("covalent url", url, filename="covalent.txt")
                exc = None

                if page_num > max_requests:
                    self.current_import.add_error(
                        Import.COVALENT_OVERLOAD, address=address, chain=self, debug_info=exc
                    )
                    log_error("Too many requests for covalent", address, url, exc)
                    break

                for rep in range(3):
                    log("rep", rep, filename="covalent.txt")
                    try:
                        time.sleep(0.25)
                        t = time.time()
                        resp = session.get(url, timeout=300)
                        log("resp time", time.time() - t, filename="covalent.txt")
                    except:
                        exc = traceback.format_exc()
                        continue

                    if resp.status_code == 429:
                        log("Got a 429, waiting", url, filename="covalent.txt")
                        time.sleep(5)
                        continue

                    try:
                        data = resp.json()
                    except:
                        exc = traceback.format_exc()
                        continue

                    try:
                        entries = data["data"]["items"]
                        done = not data["data"]["pagination"]["has_more"]
                        covalent_dump[address].extend(entries)
                        break

                    except:
                        exc = traceback.format_exc()
                        log(
                            "Weird covalent response",
                            url,
                            resp.status_code,
                            data,
                            filename="covalent.txt",
                        )

                else:
                    self.current_import.add_error(
                        Import.COVALENT_FAILURE, address=address, chain=self, debug_info=exc
                    )
                    log_error("Failed to get data from covalent", address, url, exc)
                    covalent_dump[address] = None
                    break
                if ps == 1:
                    ps = 1000
                else:
                    page_num += 1
            chain_data["covalent_dump"] = covalent_dump
            log("covalent total time", time.time() - tstart, filename="covalent.txt")

    def covalent_correction(self, chain_data):
        if "covalent_dump" not in chain_data:
            return
        addresses = chain_data["import_addresses"]
        covalent_dump = chain_data["covalent_dump"]
        log(self.name, "covalent_dump", covalent_dump, filename="covalent.txt")
        transactions = chain_data["transactions"]
        for address in addresses:
            if address not in covalent_dump:
                continue
            entries = covalent_dump[address]
            if entries is None:
                if self.name == "Fantom":
                    for txhash, T in transactions.items():
                        for row in T.grouping:
                            if address in [row[1][5], row[1][4]]:
                                row[6] |= Transfer.SUSPECT_AMOUNT
                if self.name == "Arbitrum":
                    for txhash, T in transactions.items():
                        for row in T.grouping:
                            if row[1][4] == address and row[1][5] == "network":
                                row[6] |= Transfer.SUSPECT_AMOUNT
                                log(
                                    "Setting suspect_amount",
                                    self.name,
                                    txhash,
                                    row,
                                    filename="suspects.txt",
                                )
            else:
                for entry in entries:
                    txhash = entry["tx_hash"]
                    if txhash in transactions:
                        T = transactions[txhash]
                        if self.name in ["Arbitrum", "Optimism"]:
                            # log('adjusting Arbitrum fee', txhash)
                            fee = float(entry["fees_paid"]) / pow(10, 18)
                            for row in T.grouping:
                                if row[0] == 1 and row[1][5] == "network":
                                    row[1][6] = fee
                        if self.name == "Fantom":
                            success = entry["successful"]
                            if not success:
                                for row in T.grouping:
                                    if row[1][5] != "network":
                                        row[1][6] = 0
                        to = entry["to_address"]
                        fr = entry["from_address"]
                        val = None
                        try:
                            val = float(entry["value"])
                        except:
                            pass

                        # originator is not the user, receiver is a contract --
                        # set the originator as the counterparty
                        if fr is not None and to is not None and val == 0:
                            if address != normalize_address(to):
                                T.interacted = normalize_address(to)
                            T.originator = normalize_address(fr)

    def balance_provider_correction(self, chain_data):
        to_switch = set()
        not_switch = set()
        transactions = chain_data["transactions"]
        addresses = chain_data["import_addresses"]
        timestamp_mapping = {}
        if self.name in [
            "ETH",
            "Polygon",
        ]:  # some tokens recorded as ERC20 are actually ERC721, correct w/data from simplehash
            for txhash, T in transactions.items():
                ts = int(T.ts)
                if ts not in timestamp_mapping:
                    timestamp_mapping[ts] = []
                timestamp_mapping[ts].append(txhash)

                for row in T.grouping:
                    if row[0] == 3:
                        contract = row[1][8]

                        if contract in to_switch:
                            row[1][9] = str(row[1][6])
                            row[1][6] = 1
                            row[0] = 4
                        elif contract in not_switch:
                            continue
                        else:
                            for address in addresses:
                                if address in chain_data["current_tokens"]:
                                    ct = chain_data["current_tokens"][address]
                                    if contract in ct and "nft_amounts" in ct[contract]:
                                        to_switch.add(contract)
                                        log(
                                            "Switching type to NFT, tx",
                                            txhash,
                                            "transfer",
                                            row,
                                            filename="balance_provider_correction.txt",
                                        )
                                        row[1][9] = str(row[1][6])
                                        row[1][6] = 1
                                        row[0] = 4
                                        break
                            else:
                                not_switch.add(contract)

        # Etherscan missed mints? Fix from simplehash
        log("timestamp_mapping", timestamp_mapping, filename="aux_log.txt")
        for address in addresses:
            if address not in chain_data["current_tokens"]:
                log(
                    "no current tokens for address",
                    address,
                    "on",
                    self.name,
                    filename="current_tokens_log.txt",
                )
                continue
            ct = chain_data["current_tokens"][address]
            for contract in ct:
                if "nft_amounts" in ct[contract]:
                    for nft_id in ct[contract]["nft_amounts"]:
                        acquisition_ts = ct[contract]["acquisitions"][nft_id]
                        log("acq check", contract, nft_id, acquisition_ts, filename="aux_log.txt")
                        if (
                            acquisition_ts in timestamp_mapping
                            and len(timestamp_mapping[acquisition_ts]) == 1
                        ):
                            log("acq tx found", filename="aux_log.txt")
                            T = transactions[timestamp_mapping[acquisition_ts][0]]
                            for row in T.grouping:
                                if row[0] in [4, 5] and row[1][8] == contract:
                                    break
                            else:
                                log("acq found -- creating acq transfer", filename="aux_log.txt")
                                symbol = ct[contract]["symbol"]
                                if ct[contract]["type"] == "ERC721":
                                    type = Transfer.ERC721
                                else:
                                    type = Transfer.ERC1155
                                fr = "0x0000000000000000000000000000000000000000"
                                to = address
                                val = ct[contract]["nft_amounts"][nft_id]
                                if symbol is None:
                                    symbol = "Unknown NFT"
                                row = [
                                    T.hash,
                                    T.ts,
                                    T.nonce,
                                    T.block,
                                    fr,
                                    to,
                                    val,
                                    symbol,
                                    contract,
                                    None,
                                    nft_id,
                                    0,
                                    0,
                                    None,
                                ]
                                log(
                                    "Adding minting transfer based on simplehash",
                                    type,
                                    row,
                                    filename="aux_log.txt",
                                )
                                T.append(type, row, synthetic=Transfer.MISSED_MINT)

    def extract_entity(self, tag):
        if ":" in tag:
            row_entity = tag[: tag.index(":")].upper()
        else:
            tag_parts = tag.split(" ")
            if tag_parts[-1].isdigit():
                row_entity = " ".join(tag_parts[:-1]).upper()
            else:
                row_entity = tag.upper()
        return row_entity

    def update_multiple_addresses_from_scan(self, addresses):
        log(self.name, "five address lookup", addresses, filename="address_lookups.txt")
        db_writes = []

        if len(addresses) == 0:
            return True, []
        creators = {}
        if self.name != "HECO":
            headers = {}
            if self.name in ["Moonriver", "Moonbeam"]:  # ,'Arbitrum','Optimism']:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36"
                    ),
                    "cache-control": "max-age=0",
                    "accept-language": "en-US,en;q=0.9,ru;q=0.8",
                    "upgrade-insecure-requests": "1",
                    "accept": (
                        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
                        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9"
                    ),
                }

            url = (
                self.explorer_url
                + "?module=contract&action=getcontractcreation&contractaddresses="
                + ",".join(addresses)
                + "&apikey="
                + self.api_key
            )
            log(self.name, "five address lookup url", url, filename="address_lookups.txt")
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                time.sleep(self.wait_time)
            except:
                log_error("Failed to get contract creators", url)
                self.current_import.add_error(
                    Import.NO_CREATORS, chain=self, debug_info=traceback.format_exc()
                )
                return False, []

            log(self.name, "fal 4", filename="address_lookups.txt")

            try:
                js = resp.json()
            except:
                log_error("Failed to get contract creators", url, resp.status_code, resp.content)
                self.current_import.add_error(
                    Import.NO_CREATORS, chain=self, debug_info=traceback.format_exc()
                )
                return False, []
            if "result" in js:
                data = js["result"]
                if data is not None:
                    for entry in data:
                        try:
                            creators[normalize_address(entry["contractAddress"])] = (
                                normalize_address(entry["contractCreator"])
                            )
                        except:
                            log("Unexpected data", entry, filename="address_lookups.txt")

            log(
                self.name,
                "five address lookup creator data",
                creators,
                filename="address_lookups.txt",
            )

        for address in addresses:
            creator = None
            entity = "unknown"
            if address in creators:
                creator = creators[address]
                log(
                    self.name,
                    "five address lookup, found creator",
                    address,
                    creator,
                    filename="address_lookups.txt",
                )
                entity, _ = self.get_progenitor_entity(creator)
                if entity is None:
                    badge = self.scrape_blockscan(creator)
                    if badge is not None:
                        entity = self.extract_entity(badge)
                    else:
                        entity = "unknown"
                    db_writes.append([self.name, [creator, None, None, entity, "lookup"]])
                    self.entity_map[address] = [entity, creator]
                    self.entity_map[creator] = [entity, None]

            else:
                log(
                    self.name,
                    "five address lookup, not found creator",
                    address,
                    filename="address_lookups.txt",
                )
                badge = self.scrape_blockscan(address)
                if badge is not None:
                    entity = self.extract_entity(badge)
                self.entity_map[address] = [entity, None]

            if entity != "unknown":
                log(
                    "Adding up ancestor",
                    self.name,
                    address,
                    creator,
                    entity,
                    filename="address_lookups.txt",
                )
            db_writes.append([self.name, [address, None, creator, entity, "lookup"]])

        return True, db_writes

    def scrape_blockscan(self, address):
        log("looking up on blockscan", self.name, address, filename="address_lookups.txt")
        url = "https://blockscan.com/address/" + address
        try:
            resp = requests.get(url, timeout=2)
        except:
            log("blockscan timeout", address, filename="address_lookups.txt")
            return None
        if resp.status_code != 200:
            log(
                "blockscan bad status",
                address,
                resp.status_code,
                resp.content,
                filename="address_lookups.txt",
            )
            return None

        html = resp.content.decode("utf-8")
        soup = bs4.BeautifulSoup(html, features="html.parser")
        res_els = soup.find_all("div", class_="search-result")
        top_cand = None
        for el in res_els:
            chain_match = False
            tag_el = el.find("i", class_="fa-tag")
            if tag_el is not None:
                lst = el.find("a", class_="search-result-list")
                link = lst["href"]
                badge = tag_el.parent.text
                log("blockscan badge", tag_el, chain_match, badge, filename="address_lookups.txt")
                if self.domain in link:
                    return badge
                if top_cand is None:
                    top_cand = badge
        return top_cand

    def get_contracts(self, transactions):
        contract_dict = {}
        counterparty_list = set()
        input_list = set()
        if self.wrapper is not None:
            contract_dict[self.wrapper] = None
        for transaction in transactions:
            ts = transaction.ts
            t_contracts, t_counterparties, t_inputs = transaction.get_contracts()
            for contract in t_contracts:
                if contract not in contract_dict or contract_dict[contract] is None:
                    contract_dict[contract] = ts
                elif ts > contract_dict[contract]:
                    contract_dict[contract] = ts
            counterparty_list = counterparty_list.union(t_counterparties)
            input_list = input_list.union(t_inputs)
        return contract_dict, list(counterparty_list), list(input_list)

    def filter_progenitors(self, counterparty_list):
        filtered_list = []
        for address in counterparty_list:
            address = normalize_address(address)
            if address == "0x0000000000000000000000000000000000000000":
                continue

            if not is_ethereum(address):
                continue

            entity, _ = self.get_progenitor_entity(address)
            if entity is not None:
                continue

            filtered_list.append(address)
        return filtered_list

    def update_progenitors(self, counterparty_list, pb_alloc):
        all_db_writes = []
        if self.blockscout:
            return None

        if len(counterparty_list) == 0:
            return None

        addresses_to_lookup = []
        for address in counterparty_list:
            if address == "0x0000000000000000000000000000000000000000":
                continue

            entity, _ = self.get_progenitor_entity(address)
            if entity is not None:
                continue
            addresses_to_lookup.append(normalize_address(address))
        log(self.name, "Addresses to lookup", addresses_to_lookup, filename="address_lookups.txt")
        if len(addresses_to_lookup) > 0:
            # scanner allows 5/request
            batch_cnt = len(addresses_to_lookup) // 5 + 1
            pb_per_batch = pb_alloc / batch_cnt
            offset = 0
            for batch_idx in range(batch_cnt):
                good, db_writes = self.update_multiple_addresses_from_scan(
                    addresses_to_lookup[offset : offset + 5]
                )
                log(
                    self.name,
                    "update_multiple_addresses_from_scan return",
                    good,
                    db_writes,
                    filename="address_lookups.txt",
                )
                all_db_writes.extend(db_writes)
                offset += 5
                self.update_pb(
                    "Looking up counterparties (runs slowly once): "
                    + str(batch_idx + 1)
                    + "/"
                    + str(batch_cnt),
                    pb_per_batch,
                )
                if not good:
                    break
        return all_db_writes

    def merge_transaction(self, source, destination):
        clog(source, "Merging")
        if destination.function is None:
            destination.function = source.function

        if destination.interacted is None:
            destination.interacted = source.interacted

        if destination.originator is None:
            destination.originator = source.originator

        for _, (
            type,
            sub_data,
            _transfer_id,
            _custom_treatment,
            _custom_rate,
            _custom_vaultid,
            synthetic,
            _derived,
        ) in enumerate(source.grouping):
            (
                _hash,
                _ts,
                _nonce,
                _block,
                fr,
                to,
                val,
                token,
                _token_contract,
                _coingecko_id,
                token_nft_id,
                _base_fee,
                _input_len,
                input,
            ) = sub_data
            for _, (_c_type, c_sub_data, _, _, _, _, _, _) in enumerate(destination.grouping):
                (
                    _hash,
                    _ts,
                    _nonce,
                    _block,
                    c_fr,
                    c_to,
                    c_val,
                    c_token,
                    _c_token_contract,
                    _c_coingecko_id,
                    c_token_nft_id,
                    _c_base_fee,
                    _c_input_len,
                    c_input,
                ) = c_sub_data
                if (
                    fr == c_fr
                    and to == c_to
                    and val == c_val
                    and token == c_token
                    and token_nft_id == c_token_nft_id
                    and input == c_input
                ):
                    clog(source, "Skipping transfer", sub_data, "synthetic", synthetic)
                    break
            else:
                clog(source, "Adding transfer", sub_data, "synthetic", synthetic)
                destination.append(type, sub_data, synthetic=synthetic)

    def get_current_tokens(self, _address):
        return None
