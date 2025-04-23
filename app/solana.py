import base64
import copy
import math
import random
import re
import struct
import time
import traceback
from collections import defaultdict
from hashlib import sha256

import base58
import requests
from flask import current_app
from pure25519.basic import decodepoint

from .chain import Chain
from .imports import Import
from .transaction import Transaction, Transfer
from .util import log, log_error, normalize_address


class Solana(Chain):
    # order matters, weirdest last
    NATIVE_PROGRAMS = {
        "11111111111111111111111111111111": "System Program",
        "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "Token Program",
        "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "Token Account Program",
        "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr": "Memo Program",
        "ComputeBudget111111111111111111111111111111": "Compute Budget",
        "Vote111111111111111111111111111111111111111": "Vote Program",
        "Stake11111111111111111111111111111111111111": "Stake Program",
        "BPFLoaderUpgradeab1e11111111111111111111111": "BPF Loader",
        "Ed25519SigVerify111111111111111111111111111": "Signature Verifier",
        "KeccakSecp256k11111111111111111111111111111": "Secp256k1 Program",
        "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s": "Metaplex Metadata",
    }

    JUPITER_DCA = "DCA265Vj8a9CEuX1eb1LWRnDT7uK6q1xMipnNyatn23M"

    def __init__(self):
        Chain.__init__(self, "Solana", "solscan.io", "SOL", None)
        self.explorer_url = "https://public-api.solscan.io/"
        self.domain = "explorer.solana.com"
        self.wait_time = 0.25

        self.explorer_session = requests.Session()
        self.explorer_session.headers.update(
            {"Authorization": f"Bearer {current_app.config['BLOCKDAEMON_API_KEY']}"}
        )

        self.solana_nft_data = {}
        self.solana_proxy_map = {}
        self.all_token_data = {}

        self.mode = "explorer"

    def check_presence(self, address):
        data = self.explorer_multi_request(
            {"method": "getSignaturesForAddress", "jsonrpc": "2.0", "params": [None, {"limit": 1}]},
            [address],
            timeout=30,
        )
        if len(data) > 0:
            return True
        return False

    def get_transactions(self, user, address, pb_alloc):
        log("Getting solana transactions")
        transactions = self.get_transactions_from_explorer(user, address, pb_alloc)
        log("Got solana transactions")
        return transactions

    def explorer_multi_request(
        self,
        json_template,
        query_list,
        batch_size=160,
        pb_alloc=None,
        pb_text=None,
        timeout=30,
    ):
        if len(query_list) == 0:
            log("error: query_list is empty for", json_template, filename="solana.txt")
            return {}

        rpc_url = "https://svc.blockdaemon.com/solana/mainnet/native"

        query_list = list(query_list)
        log("rpc call", json_template, len(query_list), query_list[0], filename="solana.txt")
        if batch_size is None:
            batch_size = len(query_list)

        batch_cnt = len(query_list) // batch_size
        if len(query_list) % batch_size != 0:
            batch_cnt += 1

        offset = 0
        uid_mapping = {}
        output_mapping = {}
        method = json_template["method"]
        if pb_text is not None and pb_alloc is None:
            pb_alloc = 0

        for batch_idx in range(batch_cnt):
            if pb_alloc is not None:
                pb_entry = None
                if pb_text is not None:
                    pb_entry = pb_text + ": " + str(batch_idx + 1) + "/" + str(batch_cnt)
                self.update_pb(entry=pb_entry, percent=float(pb_alloc) / batch_cnt)
            multi_explorer_request = []
            batch = query_list[offset : offset + batch_size]

            for query_datum in batch:
                uid = random.randint(1000000000, 9999999999)
                explorer_dump = copy.deepcopy(json_template)
                explorer_dump["params"][0] = query_datum
                explorer_dump["id"] = uid
                multi_explorer_request.append(explorer_dump)
                uid_mapping[uid] = query_datum

            t = time.time()
            log(
                "Sending multi dump batch",
                batch_idx,
                "out of",
                batch_cnt,
                method,
                "length",
                len(multi_explorer_request),
                filename="solana.txt",
            )
            time.sleep(1)
            try:
                log("post dump", rpc_url, multi_explorer_request, filename="solana.txt")
                headers = {"accept": "application/json", "content-type": "application/json"}
                resp = self.explorer_session.post(
                    rpc_url, timeout=timeout, json=multi_explorer_request, headers=headers
                )
            except:
                log("Request failed, timeout", traceback.format_exc(), filename="solana.txt")
                return None
            log("Timing", method, time.time() - t, filename="solana.txt")

            if resp.status_code != 200:
                log("Request failed", resp.status_code, resp.content, filename="solana.txt")
                return None

            multi_data = resp.json()
            log(
                "response meta",
                "status",
                resp.status_code,
                "len",
                len(multi_data),
                "headers",
                resp.headers,
                filename="solana.txt",
            )

            for entry in multi_data:
                if "result" not in entry or "id" not in entry:
                    log("BAD ENTRY", json_template, entry, filename="solana.txt")
                uid = entry["id"]
                output_mapping[uid_mapping[uid]] = entry["result"]

            offset += batch_size
        log("dump length", len(output_mapping), filename="solana.txt")
        return output_mapping

    def get_all_instructions(self, explorer_tx_data):
        all_instructions = []

        outer_instructions = explorer_tx_data["transaction"]["message"]["instructions"]

        for instruction in outer_instructions:
            instruction["source"] = "message"
            all_instructions.append([instruction])

        if (
            "innerInstructions" in explorer_tx_data["meta"]
            and explorer_tx_data["meta"]["innerInstructions"]
        ):
            for entry in explorer_tx_data["meta"]["innerInstructions"]:
                idx = entry["index"]
                instructions = entry["instructions"]
                for instruction in instructions:
                    instruction["source"] = "innerInstructions"
                    instruction["index"] = idx
                all_instructions[idx].extend(instructions)

        flattened_all_instructions = []
        for subset in all_instructions:
            flattened_all_instructions.extend(subset)

        return flattened_all_instructions

    def get_nft_address_from_tx(self, entry):
        pre_bal = entry["meta"]["preTokenBalances"]
        post_bal = entry["meta"]["postTokenBalances"]
        bal_change = {}
        for bal in pre_bal:
            amt = bal["uiTokenAmount"]
            if amt["decimals"] == 0:
                bal_change[bal["mint"]] = amt["uiAmount"]
        for bal in post_bal:
            amt = bal["uiTokenAmount"]
            if amt["decimals"] == 0:
                bal_change[bal["mint"]] -= amt["uiAmount"]

        cands = []
        for mint, change in bal_change.items():
            if change == 0:
                cands.append(mint)
        if len(cands) == 1:
            return cands[0]
        return None

    def find_matching_sum(
        self, total, num_list, fee, index=0, running_sum=0, accum_list=None, subsets=None
    ):
        am_spawn = False
        if subsets is None:
            subsets = []
            accum_list = []
            am_spawn = True
            if total in num_list:
                return [[num_list.index(total)]]

        if running_sum in (total - fee, total, total + fee):
            return accum_list
        if running_sum > 0 and running_sum > total + fee:
            if am_spawn:
                return subsets
            return None

        for idx, num in enumerate(num_list[index:]):
            if accum_list == [] or index + idx > accum_list[-1]:
                rv = self.find_matching_sum(
                    total,
                    num_list,
                    fee,
                    index + 1,
                    running_sum + num,
                    accum_list + [index + idx],
                    subsets=subsets,
                )
                if rv is not None and rv != [] and rv not in subsets:
                    subsets.append(rv)
        if am_spawn:
            if len(subsets) > 1:
                cull = set()
                for idx in range(0, len(subsets) - 1):
                    for idx2 in range(idx, len(subsets)):
                        subset = subsets[idx]
                        subset2 = subsets[idx2]
                        if set(subset) <= set(subset2):
                            cull.add(idx + idx2)
                        elif set(subset2) <= set(subset):
                            cull.add(idx)
                new_subsets = []
                for idx, subset in enumerate(subsets):
                    if idx not in cull:
                        new_subsets.append(subset)
                subsets = new_subsets
            return subsets
        return None

    def get_transactions_from_explorer(self, user, address, pb_alloc):
        def get_authority(info):
            if "authority" in info:
                return info["authority"]
            if "multisigAuthority" in info:
                return info["multisigAuthority"]
            raise RuntimeError("Missing authority")

        def wsol_operation(proxy, op, idx):
            if proxy in proxy_to_token_mapping:
                token = proxy_to_token_mapping[proxy]["token"]
                if token == WSOL:
                    if op == "transfer":
                        if op not in wsol_indexes[proxy]:
                            wsol_indexes[proxy][op] = []
                        wsol_indexes[proxy][op].append(idx)
                    else:
                        wsol_indexes[proxy][op] = idx

        def proxy_is_owned(proxy, ts):
            if proxy not in proxy_to_token_mapping:
                return False
            periods = proxy_to_token_mapping[proxy]["periods"]
            for period in periods:
                start, end = period
                if ts >= start and (end is None or ts <= end):
                    return True
                if start > ts:
                    break
            return False

        done = False
        limit = 1000
        tx_list = []
        self.update_pb("Getting signatures for " + address)
        json_template = {
            "method": "getSignaturesForAddress",
            "jsonrpc": "2.0",
            "params": [None, {"limit": limit}],
        }
        while not done:
            tx_multi_list = self.explorer_multi_request(
                json_template, [address], pb_text="Getting signatures for " + address, timeout=120
            )

            output = tx_multi_list[address]
            log("Retrieved signatures", output, filename="solana.txt")
            for entry in output:
                tx_list.append(entry["signature"])
            if len(output) == limit:
                json_template["params"][1]["before"] = tx_list[-1]
                time.sleep(1)
            else:
                done = True

            if "SOLANA_MAX_TX" in current_app.config:
                if len(tx_list) >= current_app.config["SOLANA_MAX_TX"]:
                    self.current_import.add_error(
                        Import.TOO_MANY_TRANSACTIONS, chain=self, address=address
                    )
                    done = True

        self.update_pb(None, pb_alloc * 0.1)

        tx_list = tx_list[::-1]
        log("tx_list", len(tx_list), tx_list, filename="solana.txt")

        all_tx_data = self.explorer_multi_request(
            {
                "method": "getTransaction",
                "jsonrpc": "2.0",
                "params": [
                    None,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed",
                        "maxSupportedTransactionVersion": 0,
                    },
                ],
            },
            tx_list,
            timeout=60,
            pb_text="Getting transactions for " + address,
            pb_alloc=pb_alloc * 0.7,
        )

        proxy_to_token_mapping = {}
        SOL = "11111111111111111111111111111111"
        SPL = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
        WSOL = "So11111111111111111111111111111111111111112"
        # collect all proxy accounts and valid proxy ownership periods OHMYGOD SOLANA WHY
        missing_owners = {}
        account_deposits = {}
        for tx_hash, tx_data in all_tx_data.items():
            if tx_data is None:
                log("NO INFO FOR TX", tx_hash, filename="solana.txt")
                continue
            ts = tx_data["blockTime"]
            log("\n\nextracting accounts from tx", tx_hash, tx_data, filename="solana.txt")
            all_instructions = self.get_all_instructions(tx_data)
            err = tx_data["meta"]["err"]
            if err is not None:
                log("Transaction fail", tx_hash, err, filename="solana.txt")
                continue

            for instruction in all_instructions:
                log("instruction", instruction, filename="solana.txt")
                if "parsed" not in instruction:
                    continue
                try:
                    parsed = instruction["parsed"]
                    programId = instruction["programId"]
                    if "type" in parsed:
                        inst_type = parsed["type"]
                        info = parsed["info"]
                        if inst_type.startswith("initializeAccount"):  # can be initializeAccount3
                            if programId == SPL:
                                owner = info["owner"]
                                if owner == address:
                                    mint = info["mint"]
                                    proxy = info["account"]
                                    if proxy not in proxy_to_token_mapping:
                                        log(
                                            "Create proxy account",
                                            proxy,
                                            ":",
                                            mint,
                                            ts,
                                            filename="solana.txt",
                                        )
                                        proxy_to_token_mapping[proxy] = {
                                            "token": mint,
                                            "periods": [[ts, None]],
                                        }
                                    else:
                                        log(
                                            "Recreate proxy account",
                                            proxy,
                                            ":",
                                            mint,
                                            ts,
                                            filename="solana.txt",
                                        )
                                        proxy_to_token_mapping[proxy]["periods"].append([ts, None])

                except:
                    log("error - failed to parse", traceback.format_exc(), filename="solana.txt")
                    continue

            for instruction in all_instructions:
                if "parsed" not in instruction:
                    continue
                try:
                    parsed = instruction["parsed"]
                    programId = instruction["programId"]

                    if "type" in parsed:
                        inst_type = parsed["type"]
                        info = parsed["info"]
                        if programId == SPL:
                            if inst_type == "setAuthority":
                                if info["authorityType"] == "accountOwner":
                                    proxy = info["account"]
                                    old = get_authority(info)
                                    new = info["newAuthority"]
                                    if address == old:
                                        proxy_to_token_mapping[proxy]["periods"][-1][1] = ts
                                        log(
                                            "Reassign proxy away",
                                            proxy,
                                            proxy_to_token_mapping[proxy],
                                        )

                                    if address == new:
                                        mint = self.get_nft_address_from_tx(tx_data)
                                        if proxy not in proxy_to_token_mapping:
                                            proxy_to_token_mapping[proxy] = {
                                                "token": mint,
                                                "periods": [[ts, None]],
                                            }
                                        else:
                                            proxy_to_token_mapping[proxy]["periods"].append(
                                                [ts, None]
                                            )
                                        log("Reassign proxy here", proxy, mint)

                            if inst_type in ("transfer", "transferChecked"):
                                destination = info["destination"]
                                source = info["source"]
                                for adr in (source, destination):
                                    if adr not in proxy_to_token_mapping:
                                        missing_owners[adr] = None

                except:
                    log("error - failed to parse", traceback.format_exc(), filename="solana.txt")
                    continue
        log(
            "proxy mapping",
            len(proxy_to_token_mapping),
            proxy_to_token_mapping,
            filename="solana.txt",
        )

        all_token_data = {}
        for proxy, data in proxy_to_token_mapping.items():
            token = data["token"]
            if token not in all_token_data:
                all_token_data[token] = {
                    "proxies": [],
                    "name": "Unknown token",
                    "symbol": "Unknown (" + token[:6] + "...)",
                    "mint_authority": token,
                    "uri": None,
                    "update_authority": token,
                    "decimals": 6,
                }
            all_token_data[token]["proxies"].append(proxy)

        log("token_to_proxies", len(all_token_data), filename="solana.txt")

        pulled_tokens = self.get_current_tokens_internal(address)
        log("pulled tokens", len(pulled_tokens), pulled_tokens, filename="solana.txt")

        missing_from_pulled = set(all_token_data.keys()) - set(pulled_tokens.keys())
        missing_from_running = set(pulled_tokens.keys()) - set(all_token_data.keys())
        log(
            "missing_from_pulled",
            len(missing_from_pulled),
            missing_from_pulled,
            filename="solana.txt",
        )
        log(
            "missing_from_running",
            len(missing_from_running),
            missing_from_running,
            filename="solana.txt",
        )

        account_info_list = self.explorer_multi_request(
            {
                "method": "getAccountInfo",
                "jsonrpc": "2.0",
                "params": [None, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            },
            list(missing_owners.keys()),
            pb_text="Getting info for token holding accounts you interacted with",
            pb_alloc=pb_alloc * 0.03,
        )
        for proxy, entry in account_info_list.items():
            try:
                data = entry["value"]["data"]["parsed"]["info"]
                owner = data["owner"]
                state = data["state"]
                if state == "initialized":
                    missing_owners[proxy] = owner
            except:
                log("Failed to get info", proxy, entry)
                continue
        log("missing_owners", missing_owners, filename="solana.txt")

        for token in list(missing_from_running):
            all_token_data[token] = {
                "proxies": [],
                "name": "Unknown token",
                "symbol": "Unknown (" + token[:6] + "...)",
                "mint_authority": token,
                "uri": None,
                "update_authority": token,
                "decimals": 6,
            }

        account_info_list = self.explorer_multi_request(
            {
                "method": "getAccountInfo",
                "jsonrpc": "2.0",
                "params": [None, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            },
            list(all_token_data.keys()),
            pb_text="Getting info for tokens at " + address,
            pb_alloc=pb_alloc * 0.02,
        )
        for token, entry in account_info_list.items():
            try:
                data = entry["value"]["data"]["parsed"]["info"]
            except:
                log("Failed to get info", token, entry)
                continue

            try:
                all_token_data[token]["decimals"] = data["decimals"]
                all_token_data[token]["mint_authority"] = data["mintAuthority"]
            except:
                log("required fields not found in info", token, data)

        token_metadata_accounts = {}
        for token in all_token_data:
            metadata_account = self.get_metadata_account(token)
            token_metadata_accounts[metadata_account] = token
        log("token_metadata_accounts", token_metadata_accounts, filename="solana.txt")
        account_info_list = self.explorer_multi_request(
            {
                "method": "getAccountInfo",
                "jsonrpc": "2.0",
                "params": [None, {"encoding": "jsonParsed", "commitment": "confirmed"}],
            },
            list(token_metadata_accounts.keys()),
            pb_text="Getting metadata for tokens at " + address,
            pb_alloc=pb_alloc * 0.05,
        )
        metadata_fails = []
        for metadata_account, entry in account_info_list.items():
            token = token_metadata_accounts[metadata_account]
            try:
                datadump = entry["value"]["data"][0]
            except:
                log("Failed to get metadata", token, metadata_account, entry)
                metadata_fails.append(token)
                continue

            log("meta dump", token, datadump)

            decoded_dump = self.unpack_metadata_account(datadump)
            log("meta dump decoded", token, metadata_account, decoded_dump)

            try:
                data = decoded_dump["data"]
                all_token_data[token]["name"] = data["name"]
                all_token_data[token]["update_authority"] = decoded_dump["update_authority"].decode(
                    "utf-8"
                )
                all_token_data[token]["symbol"] = data["symbol"]
                all_token_data[token]["uri"] = data["uri"]
            except:
                log("required fields not found in decoding", token, decoded_dump)

        log("metadata_fails", len(metadata_fails), metadata_fails)

        batch_size = 50
        batch_cnt = len(metadata_fails) // batch_size + 1
        offset = 0
        for batch_idx in range(batch_cnt):
            self.update_pb(
                "Getting metadata for more tokens at "
                + address
                + ": "
                + str(batch_idx + 1)
                + "/"
                + str(batch_cnt)
            )
            subset = metadata_fails[offset : offset + batch_size]
            if len(subset) > 0:
                time.sleep(1)
                url = "https://hyper.solana.fm/v3/token?address=" + ",".join(subset)
                try:
                    resp = requests.get(url, timeout=10)
                    data = resp.json()
                    for token, token_data in data.items():
                        if token_data is not None:
                            try:
                                all_token_data[token]["symbol"] = token_data["symbol"]
                                all_token_data[token]["name"] = token_data["name"]
                                all_token_data[token]["decimals"] = token_data["decimals"]
                                all_token_data[token]["update_authority"] = all_token_data[token][
                                    "mint_authority"
                                ] = token
                            except:
                                log(
                                    "Couldn't parse token info from solana.fm for",
                                    token,
                                    token_data,
                                )
                except:
                    log("Couldn't get token info from solana.fm", traceback.format_exc())
                    break
            offset += batch_size

        proxies = list(proxy_to_token_mapping.keys())
        proxy_tx_list = self.explorer_multi_request(
            {
                "method": "getSignaturesForAddress",
                "jsonrpc": "2.0",
                "params": [None, {"limit": 1000}],
            },
            proxies,
            pb_text="Getting signatures for token-holding accounts belonging to " + address,
            pb_alloc=pb_alloc * 0.05,
        )
        all_proxy_signatures = set()
        for proxy, proxy_transactions in proxy_tx_list.items():
            for entry in proxy_transactions:
                signature = entry["signature"]
                if (
                    signature not in all_tx_data
                ):  # retrieve tx if it hasn't already been retrieved and
                    # if it's inside a valid ownership period
                    ts = entry["blockTime"]
                    if proxy_is_owned(proxy, ts):
                        all_proxy_signatures.add(signature)
        log(
            "Additional transactions to retrieve",
            len(all_proxy_signatures),
            all_proxy_signatures,
            filename="solana.txt",
        )
        additional_tx_data = self.explorer_multi_request(
            {
                "method": "getTransaction",
                "jsonrpc": "2.0",
                "params": [
                    None,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed",
                        "maxSupportedTransactionVersion": 0,
                        "transactionDetails": "full",
                    },
                ],
            },
            all_proxy_signatures,
            timeout=60,
            pb_text="Getting transactions for token-holding accounts belonging to " + address,
            pb_alloc=pb_alloc * 0.05,
        )

        all_tx_data.update(additional_tx_data)

        self.update_pb("Processing transactions for " + address)
        tx_list = []
        for tx_hash, tx_data in all_tx_data.items():
            if tx_data is not None:
                tx_list.append([tx_hash, tx_data["blockTime"], tx_data])
        tx_list = sorted(tx_list, key=lambda tup: tup[1])
        log("tx_list length", len(tx_list), filename="solana.txt")

        prev_ts = None
        nonce = 0
        all_transactions = {}
        inst_type_counter = defaultdict(int)

        tx_sol_mismatches = []
        for tx_hash, ts, tx_data in tx_list:
            transfers = []
            unowned_transfers = []

            if ts != prev_ts:
                nonce = 1
            else:
                nonce += 1

            log("\n\nprocessing tx", tx_hash, tx_data, filename="solana.txt")
            err = tx_data["meta"]["err"]
            if err is not None:
                log("Transaction fail", tx_hash, err, filename="solana.txt")
                continue

            all_instructions = self.get_all_instructions(tx_data)

            pre_balances = tx_data["meta"]["preBalances"]
            post_balances = tx_data["meta"]["postBalances"]
            fee = tx_data["meta"]["fee"]
            log_instructions = self._log_instructions(tx_data["meta"]["logMessages"])

            sol_changes = {}
            accounts_data = tx_data["transaction"]["message"]["accountKeys"]
            add_fee = False
            if accounts_data[0]["pubkey"] == address:
                add_fee = True

            tx_accounts = []
            for entry_idx, entry in enumerate(accounts_data):
                account = entry["pubkey"]
                tx_accounts.append(account)
                sol_changes[account] = post_balances[entry_idx] - pre_balances[entry_idx]
            log("sol_changes after post/pre-balances", sol_changes, filename="solana.txt")

            tx_account_to_mint = {}
            for info in list(
                tx_data["meta"]["preTokenBalances"] + tx_data["meta"]["postTokenBalances"]
            ):
                account_idx = info["accountIndex"]
                mint = info["mint"]
                tx_account_to_mint[tx_accounts[account_idx]] = mint

            total_rewards_fee = 0
            rewards_data = tx_data["meta"]["rewards"]
            for reward in rewards_data:
                if reward["pubkey"] == address:
                    total_rewards_fee += reward["lamports"]
                else:
                    total_rewards_fee -= reward["lamports"]

            if address in sol_changes:
                sol_changes[address] += total_rewards_fee

            wsol_indexes = defaultdict(dict)
            ata_wsol_list = []  # Associated Token Accounts

            programs = defaultdict(int)
            operations = defaultdict(int)
            for instruction in all_instructions:
                log("instruction pass 3", instruction, filename="solana.txt")
                if (
                    "programId" in instruction and instruction["source"] == "message"
                ):  # only outer ones
                    programId = instruction["programId"]
                    programs[programId] += 1
                if "parsed" not in instruction:
                    continue

                try:
                    parsed = instruction["parsed"]
                    programId = instruction["programId"]
                    if "type" not in parsed:
                        continue
                    inst_type = parsed["type"]
                    operations[inst_type] += 1
                    info = parsed["info"]
                    inst_type_counter[inst_type] += 1

                    if inst_type in ("transfer", "transferChecked"):
                        source = info["source"]
                        destination = info["destination"]
                        if programId == SOL:
                            if address in (source, destination):
                                lamports = info["lamports"]
                                sol_amount = lamports / 1000000000.0
                                log("SOL transfer", source, "->", destination, ":", sol_amount)
                                if destination in account_deposits:
                                    log("Depositing SOL to owned account", destination)
                                    account_deposits[destination] += lamports
                                    wsol_operation(destination, "deposit", len(transfers))

                                if source in account_deposits:
                                    log(
                                        "WARNING Withdrawing SOL from owned account",
                                        source,
                                        filename="solana.txt",
                                    )
                                    account_deposits[source] -= lamports
                                    wsol_operation(source, "withdraw", len(transfers))

                                transfers.append(
                                    {
                                        "what": "SOL",
                                        "from": source,
                                        "to": destination,
                                        "amount": sol_amount,
                                    }
                                )
                        if programId == SPL:
                            token = None
                            authority = get_authority(info)

                            source_suspect = False
                            if proxy_is_owned(source, ts):
                                proxy = source
                                token = proxy_to_token_mapping[source]["token"]
                                source = address
                            elif authority is not None and authority != address:
                                source = authority
                            elif source != address:
                                if source in missing_owners and missing_owners[source] is not None:
                                    source = missing_owners[source]
                                else:
                                    source_suspect = True

                            destination_suspect = False
                            if proxy_is_owned(destination, ts):
                                proxy = destination
                                token = proxy_to_token_mapping[destination]["token"]
                                destination = address
                            elif authority is not None and authority != address:
                                destination = authority
                            elif destination != address:
                                if (
                                    destination in missing_owners
                                    and missing_owners[destination] is not None
                                ):
                                    destination = missing_owners[destination]
                                else:
                                    destination_suspect = True

                            if token == WSOL and proxy in ata_wsol_list:
                                continue

                            if token is not None:
                                if address in (source, destination):
                                    if "amount" in info:
                                        amount = (
                                            float(info["amount"])
                                            / 10 ** all_token_data[token]["decimals"]
                                        )
                                    elif "tokenAmount" in info:
                                        amount = info["tokenAmount"]["uiAmount"]

                                    if amount > 0:
                                        log(
                                            "Token transfer",
                                            source,
                                            "->",
                                            destination,
                                            ":",
                                            amount,
                                            "proxy",
                                            proxy,
                                            "token",
                                            token,
                                            filename="solana.txt",
                                        )
                                        transfers.append(
                                            {
                                                "what": token,
                                                "from": source,
                                                "to": destination,
                                                "amount": amount,
                                                "source_suspect": source_suspect,
                                                "destination_suspect": destination_suspect,
                                            }
                                        )

                                        if token == WSOL:
                                            wsol_operation(proxy, "transfer", len(transfers) - 1)

                                            if source == destination:
                                                log(
                                                    "WARNING WTF source=destination for WSOL",
                                                    filename="solana.txt",
                                                )
                                                continue

                                            if source == address:
                                                account_deposits[proxy] -= amount * 1000000000
                                                if account_deposits[proxy] < 0:
                                                    log(
                                                        "WARNING NEGATIVE DEPOSIT",
                                                        proxy,
                                                        account_deposits[proxy],
                                                        filename="solana.txt",
                                                    )

                                            if destination == address:
                                                account_deposits[proxy] += amount * 1000000000
                            else:
                                if inst_type in ("transfer", "transferChecked"):
                                    source = info["source"]
                                    destination = info["destination"]
                                    token = tx_account_to_mint[destination]

                                    if "amount" in info:
                                        amount = (
                                            float(info["amount"])
                                            / 10 ** all_token_data[token]["decimals"]
                                        )
                                    elif "tokenAmount" in info:
                                        amount = info["tokenAmount"]["uiAmount"]

                                    if token == WSOL:
                                        token = "SOL"

                                    # Store other transfers which might be needed (i.e. Jupiter DCA)
                                    unowned_transfers.append(
                                        {
                                            "what": token,
                                            "from": source,
                                            "to": destination,
                                            "amount": amount,
                                        }
                                    )

                    if inst_type == "createIdempotent":
                        # SPL Associated Token Account
                        if info["wallet"] == address and info["mint"] == WSOL:
                            account = info["account"]
                            if account not in ata_wsol_list:
                                ata_wsol_list.append(account)

                    if inst_type == "create":
                        if info["source"] == address:
                            account = info["account"]
                            if account not in account_deposits:
                                account_deposits[account] = 0
                                log("create", account, filename="solana.txt")

                    if inst_type in ("createAccount", "createAccountWithSeed"):
                        source = info["source"]
                        if source == address:  # and owner == address:
                            destination = info["newAccount"]
                            lamports = info["lamports"]
                            sol_amount = lamports / 1000000000.0
                            account_deposits[destination] = lamports
                            log(
                                "SOL createaccount",
                                source,
                                "->",
                                destination,
                                ":",
                                sol_amount,
                                filename="solana.txt",
                            )
                            wsol_operation(destination, "create", len(transfers))
                            transfers.append(
                                {
                                    "what": "SOL",
                                    "from": source,
                                    "to": destination,
                                    "amount": sol_amount,
                                }
                            )

                    if inst_type == "closeAccount":
                        destination = info["destination"]
                        if destination == address:  # and owner == address:
                            account = info["account"]
                            if account in account_deposits:
                                lamports = account_deposits[account]
                                sol_amount = lamports / 1000000000.0
                                if lamports <= 0:
                                    log(
                                        "WARNING CLOSE ACCOUNT, OVERDRAFT",
                                        account,
                                        lamports,
                                        filename="solana.txt",
                                    )
                                log(
                                    "SOL closeaccount",
                                    account,
                                    "->",
                                    destination,
                                    ":",
                                    sol_amount,
                                    filename="solana.txt",
                                )
                                wsol_operation(account, "close", len(transfers))
                                transfers.append(
                                    {
                                        "what": "SOL",
                                        "from": account,
                                        "to": destination,
                                        "amount": sol_amount,
                                    }
                                )
                                account_deposits[account] -= lamports

                    if inst_type == "setAuthority" and programId == SPL:
                        if info["authorityType"] == "accountOwner":
                            proxy = info["account"]
                            old = get_authority(info)
                            new = info["newAuthority"]
                            if address == old:
                                source = address
                                destination = new

                            if address == new:
                                destination = address
                                source = old

                            if address in (source, destination):
                                if proxy_is_owned(proxy, ts):
                                    token = proxy_to_token_mapping[proxy]["token"]
                                    log(
                                        "Authority reassignment",
                                        proxy,
                                        ":",
                                        token,
                                        source,
                                        "->",
                                        destination,
                                        filename="solana.txt",
                                    )
                                    transfers.append(
                                        {
                                            "what": token,
                                            "from": source,
                                            "to": destination,
                                            "amount": 1,
                                        }
                                    )

                    if inst_type in ("mintTo", "mintToChecked", "burn") and programId == SPL:
                        token = info["mint"]
                        proxy = info["account"]

                        if proxy_is_owned(proxy, ts):
                            decimals = all_token_data[token]["decimals"]
                            if inst_type == "mintToChecked":
                                amount = float(info["tokenAmount"]["uiAmount"])
                            else:
                                amount = float(info["amount"]) / float(math.pow(10, decimals))
                            if "mintTo" in inst_type:
                                log("Mint", token, amount, filename="solana.txt")
                                transfers.append(
                                    {"what": token, "from": "mint", "to": address, "amount": amount}
                                )
                            else:
                                log("Burn", token, amount, filename="solana.txt")
                                transfers.append(
                                    {"what": token, "from": address, "to": "burn", "amount": amount}
                                )

                except:
                    log("WARNING Failure to parse", traceback.format_exc(), filename="solana.txt")
                    continue

            log("sol_changes before populating from transfers", sol_changes, filename="solana.txt")
            log("transfers created from parsed", transfers, filename="solana.txt")
            for t in transfers:  # accounting balance changes, after this sol_changes should be 0
                if t["what"] == "SOL":
                    lamports = int(round(t["amount"] * 1000000000))
                    sol_changes[t["from"]] += lamports
                    sol_changes[t["to"]] -= lamports
                    log(
                        "adding sol change from transfer",
                        t["from"],
                        t["to"],
                        t["amount"],
                        lamports,
                        filename="solana.txt",
                    )

            total_unaccounted = 0
            unaccounted_changes = defaultdict(float)
            my_unaccounted_change = 0
            log("sol changes before unaccounted", sol_changes, filename="solana.txt")
            for account, amount in sol_changes.items():
                total_unaccounted += amount
                if amount != 0:
                    if account == address:
                        my_unaccounted_change += amount
                    else:
                        unaccounted_changes[account] += amount
            unaccounted_changes = dict(unaccounted_changes)

            if abs(my_unaccounted_change) > fee:
                log(
                    "Unaccounted",
                    total_unaccounted,
                    "my_unaccounted_change",
                    my_unaccounted_change,
                    "unaccounted_changes",
                    unaccounted_changes,
                    filename="solana.txt",
                )
                tx_sol_mismatches.append(tx_hash)

                pair_list = sorted(list(unaccounted_changes.items()), key=lambda tup: tup[1])
                num_list = []
                for pair in pair_list:
                    num_list.append(pair[1])
                adjusted_sol_change = -my_unaccounted_change
                log(
                    "calling find_matching_sum",
                    adjusted_sol_change,
                    num_list,
                    fee,
                    "rewards",
                    total_rewards_fee,
                    filename="solana.txt",
                )
                matching_subsets = self.find_matching_sum(adjusted_sol_change, num_list, fee)
                if len(matching_subsets) != 1:
                    log(
                        "matching_subsets",
                        my_unaccounted_change,
                        "adjusted_sol_change",
                        adjusted_sol_change,
                        "fee",
                        fee,
                        "subsets",
                        len(matching_subsets),
                        matching_subsets,
                        filename="solana.txt",
                    )
                else:
                    for idx in matching_subsets[0]:
                        account, lamports = pair_list[idx]
                        sol_amount = lamports / 1000000000.0
                        if sol_amount > 0:
                            source = address
                            destination = account
                        else:
                            source = account
                            destination = address
                            sol_amount = -sol_amount
                        log(
                            "SOL transfer via balances",
                            source,
                            "->",
                            destination,
                            ":",
                            sol_amount,
                            filename="solana.txt",
                        )
                        transfers.append(
                            {"what": "SOL", "from": source, "to": destination, "amount": sol_amount}
                        )

            if len(wsol_indexes) > 0:
                log("wsol_indexes", dict(wsol_indexes), filename="solana.txt")
                log("all transfers", transfers, filename="solana.txt")
                to_delete = []
                new_transfers = []
                for proxy, transfer_index_dict in wsol_indexes.items():
                    if "transfer" in transfer_index_dict:
                        for idx in transfer_index_dict["transfer"]:
                            log(
                                "Changing transfer item",
                                idx,
                                transfers[idx]["what"],
                                "->",
                                "SOL",
                                filename="solana.txt",
                            )
                            transfers[idx]["what"] = "SOL"
                    for inst_type in ("create", "deposit", "close"):
                        if inst_type in transfer_index_dict:
                            to_delete.append(transfer_index_dict[inst_type])
                            log(
                                "Deleting transfer",
                                inst_type,
                                transfer_index_dict[inst_type],
                                filename="solana.txt",
                            )

                for idx, t in enumerate(transfers):
                    if idx not in to_delete:
                        new_transfers.append(t)
                    else:
                        log("Ignoring transfer index", idx, filename="solana.txt")
                transfers = new_transfers

            if add_fee:
                transfers.append(
                    {"what": "SOL", "from": address, "to": "network", "amount": fee / 1000000000.0}
                )

            if len(programs) > 1:
                log("warning, multiple programs", list(programs), filename="solana.txt")

            self.all_token_data = all_token_data

            # remove same transfers going opposite ways
            if len(transfers) > 1:
                amt_mapping = {}
                to_del = set()
                for t_idx, t in enumerate(transfers):
                    what = t["what"]
                    amt = t["amount"]
                    fr = t["from"]
                    to = t["to"]
                    if fr == to:
                        continue
                    if fr == address:
                        amt = -amt
                    if what not in amt_mapping:
                        amt_mapping[what] = {}

                    if -amt in amt_mapping[what]:
                        to_del.add(t_idx)
                        to_del.add(amt_mapping[what][-amt])
                        del amt_mapping[what][-amt]
                    else:
                        amt_mapping[what][amt] = t_idx
                log("amt_mapping", amt_mapping, filename="solana.txt")
                if len(to_del) > 0:
                    new_transfers = []
                    for t_idx, t in enumerate(transfers):
                        if t_idx not in to_del:
                            new_transfers.append(t)
                    transfers = new_transfers

            if self.JUPITER_DCA in programs:
                if (
                    "OpenDca" in log_instructions
                    or "OpenDcaV2" in log_instructions
                    or "CloseDca" in log_instructions
                ):
                    for idx, t in enumerate(list(transfers)):
                        if "destination_suspect" in t:
                            # Remove DCA deposit/withdrawal
                            transfers.pop(idx)
                            break

                if unowned_transfers:
                    # Must be a DCA swap, add missing disposal
                    unowned_transfers[0]["from"] = address
                    transfers.append(unowned_transfers[0])

            if len(transfers) > 0:
                T = Transaction(user, self)
                for t in transfers:
                    token = t["what"]
                    nft_id = None
                    input_len = 0
                    input = None
                    type = Transfer.ERC20
                    fr = t["from"]
                    to = t["to"]
                    if fr == to:
                        continue

                    if token == "SOL":
                        symbol = "SOL"
                        type = Transfer.BASE
                    else:
                        token_data = all_token_data[token]
                        symbol = token_data["symbol"]
                        if token == WSOL:  # replace WSOL transfers with SOL
                            symbol = "WSOL"
                            # type = 1
                        elif all_token_data[token]["decimals"] == 0:
                            type = Transfer.ERC721
                            nft_id = all_token_data[token]["name"]
                            input_len = 200
                            input = token
                            if "update_authority" in all_token_data[token]:
                                ua = all_token_data[token]["update_authority"]
                                if ua != address:
                                    nft_id += " " + token
                                    token = ua

                    program = None
                    if programs:
                        # Only allow one program
                        non_native_progs = {
                            k: v for (k, v) in programs.items() if k not in Solana.NATIVE_PROGRAMS
                        }
                        if non_native_progs:
                            # The most used, non-native
                            program = max(non_native_progs, key=non_native_progs.get)
                        else:
                            # Or highest importance, for native
                            native_progs = [
                                k for k in reversed(Solana.NATIVE_PROGRAMS) if k in programs
                            ]
                            program = native_progs[0]

                    if program is not None:
                        T.interacted = program
                        op_str_lst = []
                        for op, cnt in operations.items():
                            op_str = op
                            if cnt > 1:
                                op_str += f"(x{cnt})"
                            op_str_lst.append(op_str)
                        T.function = ", ".join(op_str_lst)

                    row = [
                        tx_hash,
                        ts,
                        nonce,
                        ts,
                        fr,
                        to,
                        t["amount"],
                        symbol,
                        token,
                        None,
                        nft_id,
                        0,
                        input_len,
                        input,
                    ]
                    T.append(type, row)
                    if "source_suspect" in t and t["source_suspect"]:
                        # Setting suspect source in transfer
                        T.grouping[-1][6] |= Transfer.SUSPECT_FROM
                    if "destination_suspect" in t and t["destination_suspect"]:
                        # Setting suspect destination in transfer
                        T.grouping[-1][6] |= Transfer.SUSPECT_TO
                all_transactions[tx_hash] = T

        log("final all_token_data", all_token_data)
        log("inst_type_counter", inst_type_counter)
        log("tx_sol_mismatches", len(tx_sol_mismatches), tx_sol_mismatches, filename="solana.txt")
        log("all_transactions length", len(all_transactions), filename="solana.txt")
        return all_transactions

    def get_current_tokens_internal(self, address):
        tokens = {}
        resp = self.explorer_multi_request(
            {
                "method": "getTokenAccountsByOwner",
                "jsonrpc": "2.0",
                "params": [
                    None,
                    {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                    {"encoding": "jsonParsed", "commitment": "processed"},
                ],
            },
            [address],
        )
        data = resp[address]["value"]
        for entry in data:
            proxy = entry["pubkey"]
            info = entry["account"]["data"]["parsed"]["info"]
            amount = float(info["tokenAmount"]["uiAmount"])
            token = info["mint"]
            nft = False
            if info["tokenAmount"]["decimals"] == 0 and amount.is_integer():
                nft = True

            if token not in tokens:
                tokens[token] = {"amount": amount, "nft": nft, "proxies": [proxy]}
            else:
                tokens[token]["amount"] += amount
                tokens[token]["proxies"].append(proxy)

        return tokens

    # must be ran after get_transactions, not before
    def get_current_tokens(self, address):
        try:
            resp = self.explorer_multi_request(
                {
                    "method": "getAccountInfo",
                    "jsonrpc": "2.0",
                    "params": [None, {"encoding": "jsonParsed", "commitment": "confirmed"}],
                },
                [address],
            )
            data = resp[address]["value"]
            log("sol balance", data, filename="solana.txt")
            lamports = 0
            if data is not None and "lamports" in data:
                lamports = data["lamports"]
            sol_amt = lamports / 1000000000.0
            rv = {}
            rv["SOL"] = {"symbol": "SOL", "amount": sol_amt}

            tokens = self.get_current_tokens_internal(address)
            for contract, token_data in tokens.items():
                amount = token_data["amount"]
                if amount == 0:
                    continue
                gathered_token_data = self.all_token_data[contract]
                symbol = gathered_token_data["symbol"]

                if token_data["nft"]:
                    nft_id = gathered_token_data["name"]
                    if "update_authority" in gathered_token_data:
                        ua = gathered_token_data["update_authority"]
                        if ua != address:
                            nft_id += " " + contract
                            contract = ua
                    if contract not in rv:
                        rv[contract] = {"symbol": symbol, "nft_amounts": {}}

                    rv[contract]["nft_amounts"][nft_id] = amount

                    # rv[contract][nft_id] = [symbol,amount]
                else:
                    rv[contract] = {"symbol": symbol, "amount": amount}

            rv = dict(rv)
            WSOL = "So11111111111111111111111111111111111111112"
            if WSOL in rv:
                try:
                    rv["SOL"]["amount"] += rv[WSOL]["amount"]
                    del rv[WSOL]
                except:
                    pass

            log("current tokens to store", rv, filename="solana.txt")
            return rv
        except:
            log_error("SOLANA: Failed to get_current_tokens", address)
            return None

    def get_contracts(self, transactions):
        return [], [], []

    def correct_transactions(self, address, transactions, pb_alloc):
        return transactions

    # https://chainstack.com/the-mystery-of-solana-metaplex-nft-metadata-encoding/
    def unpack_metadata_account(self, data):
        data = base64.b64decode(data)

        assert data[0] == 4
        i = 1
        source_account = base58.b58encode(bytes(struct.unpack("<" + "B" * 32, data[i : i + 32])))
        i += 32
        mint_account = base58.b58encode(bytes(struct.unpack("<" + "B" * 32, data[i : i + 32])))
        i += 32
        name_len = struct.unpack("<I", data[i : i + 4])[0]
        i += 4
        name = struct.unpack("<" + "B" * name_len, data[i : i + name_len])
        i += name_len
        symbol_len = struct.unpack("<I", data[i : i + 4])[0]
        i += 4
        symbol = struct.unpack("<" + "B" * symbol_len, data[i : i + symbol_len])
        i += symbol_len
        uri_len = struct.unpack("<I", data[i : i + 4])[0]
        i += 4
        uri = struct.unpack("<" + "B" * uri_len, data[i : i + uri_len])
        i += uri_len
        fee = struct.unpack("<h", data[i : i + 2])[0]
        i += 2
        has_creator = data[i]
        i += 1
        creators = []
        verified = []
        share = []
        if has_creator:
            creator_len = struct.unpack("<I", data[i : i + 4])[0]
            i += 4
            for _ in range(creator_len):
                creator = base58.b58encode(bytes(struct.unpack("<" + "B" * 32, data[i : i + 32])))
                creators.append(creator)
                i += 32
                verified.append(data[i])
                i += 1
                share.append(data[i])
                i += 1
        primary_sale_happened = bool(data[i])
        i += 1
        is_mutable = bool(data[i])
        metadata = {
            "update_authority": source_account,
            "mint": mint_account,
            "data": {
                "name": bytes(name).decode("utf-8").strip("\x00"),
                "symbol": bytes(symbol).decode("utf-8").strip("\x00"),
                "uri": bytes(uri).decode("utf-8").strip("\x00"),
                "seller_fee_basis_points": fee,
                "creators": creators,
                "verified": verified,
                "share": share,
            },
            "primary_sale_happened": primary_sale_happened,
            "is_mutable": is_mutable,
        }
        return metadata

    def get_metadata_account(self, mint_key):
        metaplex = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
        METADATA_PROGRAM_ID = PublicKey(metaplex)

        pk = PublicKey.find_program_address(
            [b"metadata", bytes(METADATA_PROGRAM_ID), bytes(PublicKey(mint_key))],
            METADATA_PROGRAM_ID,
        )[0]

        metadata_address = str(pk)
        return metadata_address

    def balance_provider_correction(self, chain_data):
        return

    def get_progenitor_entity(self, address):
        if address in Solana.NATIVE_PROGRAMS:
            return Solana.NATIVE_PROGRAMS[address], None
        return super().get_progenitor_entity(address)

    def update_progenitors(self, counterparty_list, pb_alloc):
        all_db_writes = []
        if len(counterparty_list) == 0:
            return None

        addresses_to_lookup = []
        for address in counterparty_list:
            if address in Solana.NATIVE_PROGRAMS:
                continue

            entity, _ = self.get_progenitor_entity(address)
            if entity is not None:
                continue
            addresses_to_lookup.append(normalize_address(address))
        log(self.name, "Addresses to lookup", addresses_to_lookup, filename="address_lookups.txt")

        if len(addresses_to_lookup) > 0:
            batch_size = 100
            batch_cnt = len(addresses_to_lookup) // batch_size + 1
            pb_per_batch = pb_alloc / batch_cnt
            offset = 0
            for batch_idx in range(batch_cnt):
                good, db_writes = self.update_multiple_addresses_from_scan(
                    addresses_to_lookup[offset : offset + batch_size]
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

    def update_multiple_addresses_from_scan(self, addresses):
        log(self.name, "multi address lookup", addresses, filename="address_lookups.txt")
        db_writes = []

        if len(addresses) == 0:
            return True, []

        url = "https://hyper.solana.fm/v2/address/" + ",".join(addresses)
        try:
            resp = requests.get(url, timeout=120)
            time.sleep(0.5)
        except:
            log_error("Failed to get contract creators", url)
            self.current_import.add_error(
                Import.NO_CREATORS, chain=self, debug_info=traceback.format_exc()
            )
            return False, []

        try:
            data = resp.json()
        except:
            log_error("Failed to get contract creators", url, resp.status_code, resp.content)
            self.current_import.add_error(
                Import.NO_CREATORS, chain=self, debug_info=traceback.format_exc()
            )
            return False, []
        if data is None:
            return False, []

        try:
            for address, entry in data.items():
                entity = "unknown"
                if entry is not None and "FriendlyName" in entry:
                    entity = entry["FriendlyName"]
                    self.entity_map[address] = [entity, None]
                db_writes.append([self.name, [address, None, None, entity, "lookup"]])

        except:
            log("Unexpected data", data, filename="address_lookups.txt")
            return False, []

        return True, db_writes

    def merge_transaction(self, source, destination):
        if destination.function is None:
            destination.function = source.function

        if destination.interacted is None:
            destination.interacted = source.interacted

        if destination.originator is None:
            destination.originator = source.originator

        for _source_idx, (
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
            for dest_idx, (_c_type, c_sub_data, _, _, _, _, _, _) in enumerate(
                destination.grouping
            ):
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
                    val == c_val
                    and token == c_token
                    and token_nft_id == c_token_nft_id
                    and input == c_input
                ):
                    if fr == c_fr and to == c_to:
                        # Skipping transfer
                        break
                    if fr == c_fr or to == c_to:
                        if source.my_address(fr) and not source.my_address(c_fr):
                            # Updating transfer from address
                            destination.grouping[dest_idx][4] = fr
                            break
                        if source.my_address(to) and not source.my_address(c_to):
                            # Updating transfer to address
                            destination.grouping[dest_idx][5] = to
                            break
            else:
                # Adding transfer
                destination.append(type, sub_data, synthetic=synthetic)

    def _log_instructions(self, log_messages):
        log_instructions = defaultdict(int)
        if log_messages is None:
            log_messages = []

        for line in log_messages:
            match = re.search(r"^Program log: Instruction: (.*)", line)
            if match:
                instruction = match.group(1)
                log_instructions[instruction] += 1

        return log_instructions


class PublicKey:
    LENGTH = 32
    """Constant for standard length of a public key."""

    def __init__(self, value):
        """Init PublicKey object."""
        self._key = None
        if isinstance(value, str):
            try:
                self._key = base58.b58decode(value)
            except ValueError as err:
                raise ValueError("invalid public key input:", value) from err
            if len(self._key) != self.LENGTH:
                raise ValueError("invalid public key input:", value)
        elif isinstance(value, int):
            self._key = bytes([value])
        else:
            self._key = bytes(value)

        if len(self._key) > self.LENGTH:
            raise ValueError("invalid public key input:", value)

    def __bytes__(self) -> bytes:
        """Public key in bytes."""
        if not self._key:
            return bytes(self.LENGTH)
        return self._key if len(self._key) == self.LENGTH else self._key.rjust(self.LENGTH, b"\0")

    def __eq__(self, other) -> bool:
        """Equality definition for PublicKeys."""
        return False if not isinstance(other, PublicKey) else bytes(self) == bytes(other)

    def __repr__(self) -> str:
        """Representation of a PublicKey."""
        return str(self)

    def __str__(self) -> str:
        """String definition for PublicKey."""
        return self.to_base58().decode("utf-8")

    def to_base58(self) -> bytes:
        """Public key in base58."""
        return base58.b58encode(bytes(self))

    @staticmethod
    def create_with_seed(from_public_key, seed, program_id):
        """Derive a public key from another key, a seed, and a program ID."""
        raise NotImplementedError("create_with_seed not implemented")

    @staticmethod
    def create_program_address(seeds, program_id):
        """Derive a program address from seeds and a program ID."""
        buffer = b"".join(seeds + [bytes(program_id), b"ProgramDerivedAddress"])
        hashbytes = sha256(buffer).digest()
        if not PublicKey._is_on_curve(hashbytes):
            return PublicKey(hashbytes)
        raise Exception("Invalid seeds, address must fall off the curve")

    @staticmethod
    def find_program_address(seeds, program_id):
        nonce = 255
        while nonce != 0:
            try:
                buffer = seeds + [nonce.to_bytes(1, byteorder="little")]
                address = PublicKey.create_program_address(buffer, program_id)
            except Exception:
                nonce -= 1
                continue
            return address, nonce
        raise KeyError("Unable to find a viable program address nonce")

    @staticmethod
    def _is_on_curve(pubkey_bytes):
        """Verify the point is on curve or not."""
        try:
            decodepoint(pubkey_bytes)
            return True
        except:
            return False
