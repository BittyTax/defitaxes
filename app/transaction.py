# -*- coding: utf-8 -*-
import sys
import time
import traceback
from collections import defaultdict

from sortedcontainers import SortedDict

from .category import Category
from .fiat_rates import Twelve
from .util import clog, decustom, log, normalize_address


class Transfer:
    # transfer categories used in classifier
    SENT = 0
    RECEIVED = 1
    MINTED = 2
    FROM_BRIDGE = 3
    TO_BRIDGE = 4
    UNSTAKED_LP = 5
    BURNED = 6
    ZERO_VALUED = 8
    STAKED_LP = 9
    NFT_IN = 10
    NFT_OUT = 11
    REDEEMED_LP = 12
    REWARDS_LP = 13
    ERROR = 14
    UNVAULTED = 15
    INTERACTED = 16
    MINTED_NFT = 17
    SELF = 18

    # synthetic transfer types fr, to, val, token, token_contract, token_nft_id
    SUSPECT_FROM = 1 << 20
    SUSPECT_TO = 1 << 21
    SUSPECT_AMOUNT = 1 << 22
    SUSPECT_WHAT = 1 << 23
    SUSPECT_NFTID = 1 << 24

    FEE = 1
    WRAP = 2
    REBASE = 3
    MISSED_MINT = 4
    ARBITRUM_BRIDGE = 5

    BASE = 1
    INTERNAL = 2
    ERC20 = 3
    ERC721 = 4
    ERC1155 = 5
    UPLOAD_IN = 20
    UPLOAD_OUT = 21
    UPLOAD_FEE = 22

    name_map = {
        SENT: "sent",
        RECEIVED: "received",
        MINTED: "minted",
        FROM_BRIDGE: "from bridge",
        TO_BRIDGE: "to bridge",
        UNSTAKED_LP: "unstaked",
        BURNED: "burned",
        ZERO_VALUED: "zero-valued",
        STAKED_LP: "staked",
        REDEEMED_LP: "redeemed",
        NFT_IN: "NFTs received",
        NFT_OUT: "NFTs sent",
        REWARDS_LP: "rewards",
        ERROR: "error",
        UNVAULTED: "unvaulted",
        INTERACTED: "interacted",
        MINTED_NFT: "minted NFT",
        SELF: "self-transfer",
    }

    ALL_FIELDS = [
        "type",
        "from_me",
        "fr",
        "to_me",
        "to",
        "amount",
        "what",
        "symbol",
        "coingecko_id",
        "input_len",
        "rate_found",
        "rate",
        "rate_source",
        "free",
        "treatment",
        "input",
        "amount_non_zero",
        "input_non_zero",
        "id",
        "token_nft_id",
        "vault_id",
        "synthetic",
        "changed",
    ]

    def __init__(
        self,
        id,
        type,
        from_me,
        fr,
        to_me,
        to,
        val,
        token_contract,
        token_name,
        coingecko_id,
        token_nft_id,
        input_len,
        rate_found,
        rate,
        rate_source,
        base_fee,
        input=None,
        treatment=None,
        synthetic=False,
        vault_id=None,
        custom_treatment=None,
        custom_rate=None,
        custom_vaultid=None,
    ):
        if val is None or val == "":
            val = 0
        if "," in str(val):
            val = float(val.replace(",", ""))
        if input_len is None:
            input_len = 0
        if base_fee is None:
            base_fee = 0
        self.type = type
        self.from_me = from_me
        self.fr = fr
        self.to_me = to_me
        self.to = to
        self.amount = val
        self.amount_non_zero = val > 0
        self.what = token_contract
        self.coingecko_id = coingecko_id
        self.symbol = token_name
        self.input_len = input_len
        self.input_non_zero = input_len > 2
        self.rate_found = rate_found
        self.rate = rate
        self.rate_source = rate_source
        self.free = base_fee == 0
        self.treatment = treatment
        self.input = input
        self.outbound = from_me and not to_me
        self.token_nft_id = token_nft_id
        self.id = id
        self.synthetic = synthetic
        self.vault_id = vault_id
        self.custom_treatment = custom_treatment
        self.custom_rate = custom_rate
        self.custom_vaultid = custom_vaultid
        self.changed = None
        self.derived_data = None

    def __getitem__(self, key):
        return getattr(self, key)

    def to_dict(self):
        dct = {}
        for f in Transfer.ALL_FIELDS:
            dct[f] = self[f]
        return dct

    def __str__(self):
        return str(self.to_dict())

    def __repr__(self):
        return self.__str__()

    def set_default_vaultid(self, cp_name):
        if self.outbound:
            adr = self.to
        else:
            adr = self.fr

        if cp_name == adr:
            self.vault_id = cp_name[:6]
        else:
            if adr is not None:
                self.vault_id = cp_name[:6] + " " + adr[:6]
            else:
                self.vault_id = "Network"


class Transaction:
    IGNORE = 0
    BURN = 1
    SELL = 2
    BUY = 3
    GIFT = 4
    MAPPED_FIELDS = [
        "from_me",
        "fr",
        "to_me",
        "to",
        "amount",
        "what",
        "type",
        "rate_found",
        "free",
        "symbol",
        "amount_non_zero",
        "input_non_zero",
    ]

    def __init__(
        self,
        user,
        chain,
        _hash=None,
        ts=None,
        block=None,
        nonce=None,
        txid=None,
        custom_type_id=None,
        custom_color_id=None,
        custom_note=None,
        manual=None,
        upload_id=None,
    ):
        self.hash = hash
        self.ts = ts
        self.type = None
        self.block = block
        self.nonce = nonce
        self.grouping = []
        self.chain = chain
        self.upload_id = upload_id
        self.main_asset = chain.main_asset
        self.user = user
        self.total_fee = None
        self.fee_transfer = None
        self.combo = None
        self.transaction_value = None
        self.classification_certainty_level = 0
        self.rate_inferred = False
        self.balanced = False
        self.txid = txid
        self.custom_type_id = custom_type_id
        self.custom_color_id = custom_color_id
        self.custom_note = custom_note
        if manual == 1:
            self.manual = 1
        else:
            self.manual = 0
        self.interacted = None
        self.function = None
        self.originator = None

        self.derived_data = None
        self.success = None
        self.changed = None
        self.fiat_rate = 1
        self.minimized = None
        self.counter_parties = {}
        self.transfers = SortedDict()
        self.mappings = {}
        self.amounts = {}
        self.in_cnt = 0
        self.out_cnt = 0

    def append(
        self,
        cl,
        row,
        transfer_id=None,
        custom_treatment=None,
        custom_rate=None,
        custom_vaultid=None,
        synthetic=0,
        derived=None,
        prepend=False,
    ):
        hash, ts, nonce, block = row[0:4]
        if hash == self.chain.hif:
            log(
                "Add row to tx",
                hash,
                cl,
                row,
                "callstack",
                traceback.format_stack(),
                filename="specific_tx.txt",
            )
        self.hash = hash
        self.ts = ts
        if nonce is not None:
            self.nonce = int(nonce)
        if block is not None:
            self.block = int(block)

        if prepend:
            self.grouping.insert(
                0,
                [
                    cl,
                    row,
                    transfer_id,
                    custom_treatment,
                    custom_rate,
                    custom_vaultid,
                    synthetic,
                    derived,
                ],
            )
        else:
            self.grouping.append(
                [
                    cl,
                    row,
                    transfer_id,
                    custom_treatment,
                    custom_rate,
                    custom_vaultid,
                    synthetic,
                    derived,
                ]
            )

    def finalize(self, coingecko_rates, fiat_rates, signatures, store_derived=False):
        t_fin = [0, 0, 0, 0, 0]
        self.total_fee = 0
        self.transfers = SortedDict()
        null_addr = "0x0000000000000000000000000000000000000000"
        counter_parties = {}
        potentates = {}

        amounts = defaultdict(float)
        dd = self.derived_data
        use_dd = dd is not None and not store_derived

        self.mappings = {}
        for key in Transaction.MAPPED_FIELDS:  # .keys():
            self.mappings[key] = defaultdict(list)

        if store_derived and dd is not None:  # and dd['certainty'] is not None:
            if dd["certainty"] is not None:  # it's not a new transaction
                self.changed = {}
            else:
                self.changed = "NEW"

        tx_input = None
        for _, (
            type,
            sub_data,
            id,
            custom_treatment,
            custom_rate,
            custom_vaultid,
            synthetic,
            derived,
        ) in enumerate(self.grouping):
            t0 = time.time()
            (
                hash,
                ts,
                _nonce,
                block,
                fr,
                to,
                val,
                token,
                token_contract,
                coingecko_id,
                token_nft_id,
                base_fee,
                input_len,
                input,
            ) = sub_data
            fr = normalize_address(fr)
            to = normalize_address(to)
            self.hash = hash
            self.ts = ts
            if block is not None:
                self.block = block

            if token_contract is None:
                token_contract = self.main_asset

            assert id is not None

            clog(self, "finalize", hash, dd, token_contract, fiat_rates.fiat)
            if token_contract == fiat_rates.fiat:
                # rate_found, rate, rate_source = 1, 1, 'fiat'  # rate updated on the client
                rate_found, rate, rate_source = (
                    1,
                    1.0 / fiat_rates.lookup_rate(token_contract, ts),
                    "fiat",
                )  # rate updated on the client
                coingecko_id = fiat_rates.fiat
            elif token_contract in Twelve.FIAT_SYMBOLS:
                # rate_found, rate, rate_source = 1, 1, 'fiat'  # rate updated on the client
                rate_found, rate, rate_source = (
                    1,
                    1.0 / fiat_rates.lookup_rate(token_contract, ts),
                    "fiat-other",
                )  # rate updated on the client
                coingecko_id = token_contract
            elif coingecko_id is not None:
                tc0 = time.time()
                rate_found, rate, rate_source = coingecko_rates.lookup_rate_by_id(coingecko_id, ts)
                tc1 = time.time()
                t_fin[3] += tc1 - tc0
                log(
                    "Looked up coingecko rate in finalize",
                    hash,
                    id,
                    coingecko_id,
                    ts,
                    rate_found,
                    rate,
                    rate_source,
                )
                if token_contract is None:
                    token_contract = coingecko_id
            elif use_dd:
                coingecko_id, rate_found, rate, rate_source = (
                    derived["coingecko_id"],
                    derived["rate_found"],
                    derived["rate"],
                    derived["rate_source"],
                )
            else:
                tc2 = time.time()
                coingecko_id = coingecko_rates.lookup_id(self.chain.name, token_contract)
                tc3 = time.time()
                t_fin[4] += tc3 - tc2
                rate_found, rate, rate_source = coingecko_rates.lookup_rate(
                    self.chain.name, token_contract, ts
                )  # can't use custom rates here because they'll get saved into derived data
            t1 = time.time()
            t_fin[0] += t1 - t0

            _decustomed_input, is_custom_op = decustom(input)
            if not is_custom_op:
                passed_input = None
            else:
                passed_input = input

            self_transfer = False
            skip_transfer_cps = False
            from_me = self.my_address(fr)
            to_me = self.my_address(to)
            if from_me and to_me:
                skip_transfer_cps = True

            from_me_strict = self.my_address(fr, strict=True)
            to_me_strict = self.my_address(to, strict=True)
            if from_me_strict and to_me_strict:
                self_transfer = True

            clog(
                self,
                "Making transfer",
                val,
                token_contract,
                token,
                coingecko_id,
                rate_found,
                rate,
                rate_source,
            )
            transfer = Transfer(
                id,
                type,
                from_me_strict,
                fr,
                to_me_strict,
                to,
                val,
                token_contract,
                token,
                coingecko_id,
                token_nft_id,
                input_len,
                rate_found,
                rate,
                rate_source,
                base_fee,
                custom_treatment=custom_treatment,
                custom_rate=custom_rate,
                custom_vaultid=custom_vaultid,
                input=passed_input,
                synthetic=synthetic,
            )
            t2 = time.time()
            t_fin[1] += t2 - t1

            if use_dd:
                transfer.derived_data = derived

                if store_derived:
                    transfer.changed = {}
                    if coingecko_id != derived["coingecko_id"]:
                        transfer.changed["Coingecko ID"] = (derived["coingecko_id"], coingecko_id)
                    if rate != derived["rate"]:
                        transfer.changed["Rate"] = (derived["rate"], rate)

            if transfer.synthetic in [transfer.MISSED_MINT, transfer.REBASE]:
                transfer.treatment = "gift"

            self.transfers[id] = transfer

            log(
                "tx hash",
                self.hash,
                _,
                input_len,
                input,
                "transfer conditions",
                transfer.synthetic,
                Transfer.FEE,
                self_transfer,
                dd is None,
                self.chain,
            )

            if transfer.synthetic != Transfer.FEE:  # mostly ignore fee transfer
                if (
                    self.chain.name == "Solana"
                    and transfer.what == "SOL"
                    and transfer.amount < 0.03
                ):  # ignore SOL dust
                    pass
                else:
                    for key in Transaction.MAPPED_FIELDS:
                        self.mappings[key][transfer[key]].append(id)

                    if not self_transfer:
                        if val != 0:
                            if from_me_strict:
                                amounts[token_contract] -= val

                            if to_me_strict:
                                amounts[token_contract] += val

                if not skip_transfer_cps:
                    if not use_dd:
                        if self.chain.name != "Solana":
                            for addr in [
                                fr,
                                to,
                            ]:  # gather potential counterparties from transfer to/from addresses,
                                # superceeded later by self.interacted -- the contract address
                                if (
                                    not self.my_address(addr)
                                    and addr != null_addr
                                    and addr[:2].lower() == "0x"
                                    and addr not in self.chain.transferred_tokens
                                ):
                                    prog_name, prog_addr = self.chain.get_progenitor_entity(addr)
                                    if prog_addr is None or prog_addr == "None":
                                        prog_addr = addr
                                    clog(
                                        self,
                                        "Looked up progenitor for",
                                        addr,
                                        "got",
                                        prog_addr,
                                        prog_name,
                                    )

                                    if input_len > 2:
                                        tx_input = input
                                    if prog_name is not None:
                                        potentates[prog_addr] = [prog_name, None, None, 1, addr]

                    if self.chain.name == "Solana" and input_len == 200:  # input is nft address
                        transfer.input = input
                        log("setting input to", input)

            else:
                self.total_fee = transfer.amount
                self.fee_transfer = transfer
                self.originator = transfer.fr
            t3 = time.time()
            t_fin[2] += t3 - t2

        tt0 = time.time()
        clog(self, "Making counterparties")
        if use_dd:
            if dd["cp_progenitor"] is not None:
                counter_parties[dd["cp_progenitor"]] = [
                    dd["cp_name"],
                    dd["sig_hex"],
                    dd["sig_decoded"],
                    1,
                    dd["cp_address"],
                ]
            clog(self, "Got cps from dd", counter_parties)
        else:
            clog(self, "Interacted", self.interacted)
            if self.interacted is not None:
                if self.interacted == self.chain.wrapper:
                    prog_name = "WRAPPER"
                    prog_addr = self.interacted
                else:
                    prog_name, prog_addr = self.chain.get_progenitor_entity(self.interacted)
                if prog_name is None:
                    prog_name = "unknown"
                if prog_addr is None:
                    prog_addr = self.interacted
                decoded_sig, sig = None, None
                clog(self, "Function", self.function, "input", tx_input)

                if self.function is not None:
                    if self.function[:2] == "0x":  # sometimes it's just plain wrong
                        decoded_sig, unique, sig = signatures.lookup_signature(self.function)
                    else:
                        decoded_sig, sig = self.function, self.function

                clog(self, "Sig1", decoded_sig, sig)

                if tx_input is not None:
                    decoded_sig_cand, unique, sig_cand = signatures.lookup_signature(tx_input)
                    clog(self, "Sig2", decoded_sig_cand, unique, sig_cand)
                    if unique or decoded_sig is None:
                        decoded_sig, sig = decoded_sig_cand, sig_cand
                        self.function = decoded_sig
                counter_parties[prog_addr] = [prog_name, sig, decoded_sig, 1, self.interacted]
                clog(self, "CPs", counter_parties)

                # if we interacted with a token, it's probably a transfer, and not a useful
                # counterparty sig is none if originator is not the user -- i.e. if someone else
                # transferred stuff to user, "interacted" is present, but sig is None
                if self.interacted in self.chain.transferred_tokens and (
                    decoded_sig is None or "transfer" in decoded_sig.lower()
                ):
                    minted = self.lookup({"to_me": True, "fr": null_addr, "amount_non_zero": True})
                    burned = self.lookup(
                        {"from_me": True, "to": null_addr, "amount_non_zero": True}
                    )
                    received_nonzero = self.lookup({"to_me": True, "amount_non_zero": True})
                    sent_nonzero = self.lookup({"from_me": True, "amount_non_zero": True})
                    clog(
                        self,
                        "self.interacted in transferred tokens",
                        "potentates",
                        potentates,
                        len(minted),
                        len(burned),
                        len(received_nonzero),
                        len(sent_nonzero),
                    )
                    if (
                        len(minted) == 0
                        and len(burned) == 0
                        and len(received_nonzero) + len(sent_nonzero) == 1
                    ):
                        if self.interacted in potentates:
                            clog(self, "Removed token CP 1")
                            del potentates[self.interacted]
                        if prog_addr in potentates:
                            clog(self, "Removed token CP 2")
                            del potentates[prog_addr]
                        counter_parties = potentates

            elif self.manual:
                prog_name, prog_addr = self.chain.get_progenitor_entity("0xmanual")
                if prog_name is None:
                    prog_name = "Manual transaction"
                if prog_addr is None:
                    prog_addr = "0xmanual"
                decoded_sig, sig = None, None
                if self.function is not None:
                    decoded_sig, sig = self.function, self.function
                counter_parties[prog_addr] = [prog_name, sig, decoded_sig, 1, prog_addr]
            else:
                counter_parties = potentates
        tt1 = time.time()
        t_fin.append(tt1 - tt0)

        if len(counter_parties) > 1:  # remove unknowns
            new_cps = {}
            for prog_addr, cp_data in counter_parties.items():
                if cp_data[0] is not None and cp_data[0].lower() != "unknown":
                    new_cps[prog_addr] = cp_data
            counter_parties = new_cps

        if len(counter_parties) > 1:
            counter_parties = {}

        log("finalizing", self.hash, counter_parties)

        self.counter_parties = counter_parties

        cp_name = "unknown"
        if len(self.counter_parties):
            cp_name = list(self.counter_parties.values())[0][0]
        for transfer in self.transfers.values():
            transfer.set_default_vaultid(cp_name)

        self.amounts = dict(amounts)

        out_cnt = 0
        in_cnt = 0
        for _k, v in self.amounts.items():
            if v > 0:
                in_cnt += 1
            if v < 0:
                out_cnt += 1
        self.in_cnt = in_cnt
        self.out_cnt = out_cnt
        tt2 = time.time()
        t_fin.append(tt2 - tt1)
        return t_fin

    # finds all matching transfers by a dictionary of AND-ed field=value pairs
    def lookup(self, fv_pairs, count_only=False):
        if self.hash == self.chain.hif:
            log("transfer lookup", fv_pairs)

        matching_ids = None
        for field, value in fv_pairs.items():
            assert field in Transaction.MAPPED_FIELDS
            mapping = self.mappings[field]
            if isinstance(value, (list, set)):  # find everyone that's in the list
                subset = set()
                value_list = value

                for val in mapping.keys():
                    if val in value_list:
                        subset = subset.union(mapping[val])
                if matching_ids is None:
                    matching_ids = subset
                else:
                    matching_ids = matching_ids.intersection(subset)
            else:
                if value not in mapping:
                    matching_ids = set()
                    break
                if matching_ids is None:
                    matching_ids = set(mapping[value])
                else:
                    matching_ids = matching_ids.intersection(mapping[value])
            if len(matching_ids) == 0:
                break
        if count_only:
            return len(matching_ids)
        outs = []
        for id in matching_ids:
            outs.append(self.transfers[id])
        return outs

    def tval(self, transfer, field):
        return transfer[Transfer.ALL_FIELDS[field]]

    def __str__(self):
        if self.hash is not None:
            rv = "HASH:" + str(self.hash) + ", TIMESTAMP:" + str(self.ts)
            for transfer in self.transfers.values():
                rv += str(transfer) + "\n"
        else:
            return str(self.grouping)
        return rv

    def __repr__(self):
        return self.__str__()

    def my_address(self, address, strict=False):
        return self.user.check_user_address(self.chain.name, address, strict=strict)

    def get_contracts(self):
        contract_list = set()
        counterparty_list = set()
        input_list = set()

        for _type, sub_data, _, _, _, _, _, _ in self.grouping:
            (
                _hash,
                _ts,
                _nonce,
                _block,
                fr,
                to,
                _val,
                _token,
                token_contract,
                _coingecko_id,
                _token_nft_id,
                _base_fee,
                input_len,
                input,
            ) = sub_data
            if token_contract is not None:
                contract_list.add(token_contract)
            if self.chain.name != "Solana":
                if input_len is not None and input_len > 2:  # ignore 0x
                    if input is not None:
                        input_list.add(input)

                # it's possible we don't have the transfer that called the contract
                if not self.my_address(to):
                    counterparty_list.add(to)

                if not self.my_address(fr):
                    counterparty_list.add(fr)
            if self.chain.name == "Solana":
                if self.interacted is not None:
                    counterparty_list = [self.interacted]
                if self.function is not None:
                    input_list = self.function.split(",")

        return contract_list, counterparty_list, input_list

    def infer_and_adjust_rates(self, user, coingecko_rates, skip_adjustment=False):
        do_print = False
        if self.hash == self.chain.hif:
            do_print = True
            log("infer and adjust rates for tx", self.txid)
            log("transaction", self)

        if not self.balanced:
            if do_print:
                log("tx not balanced")
            return

        in_cnt = 0
        out_cnt = 0
        amounts = defaultdict(float)
        symbols = {}

        usd_present = False

        for transfer in self.transfers.values():
            if do_print:
                log("Proc transfer", transfer)
            if transfer.synthetic == Transfer.FEE:
                continue
            if self.my_address(transfer.fr, strict=True) and self.my_address(
                transfer.to, strict=True
            ):
                continue
            val = transfer.amount
            lookup_contract = transfer.what
            if (
                transfer.type == 5
            ):  # multi-tokens are too different from each other to assume all same
                lookup_contract = transfer.what + "_" + str(transfer.token_nft_id)

            if val > 0:
                if transfer.treatment == "buy":
                    in_cnt += 1
                    amounts[lookup_contract] += val
                    symbols[lookup_contract] = {
                        "symbol": transfer.symbol,
                        "rate": transfer.rate,
                        "rate_found": transfer.rate_found,
                        "rate_source": transfer.rate_source,
                        "coingecko_id": transfer.coingecko_id,
                    }
                elif transfer.treatment == "sell":
                    out_cnt += 1
                    amounts[lookup_contract] -= val
                    symbols[lookup_contract] = {
                        "symbol": transfer.symbol,
                        "rate": transfer.rate,
                        "rate_found": transfer.rate_found,
                        "rate_source": transfer.rate_source,
                        "coingecko_id": transfer.coingecko_id,
                    }
                if transfer.coingecko_id == user.fiat:
                    usd_present = True
                if transfer.type in [4, 5]:
                    skip_adjustment = True
        if do_print:
            log("infer_and_adjust_rates symbols", symbols)
            log("infer_and_adjust_rates amounts", amounts)
        combo = (out_cnt, in_cnt)

        if combo[0] > 0 and combo[1] > 0:
            add_rate_for = None
            bad_out = 0
            bad_in = 0
            iffy_out = 0
            iffy_in = 0
            good_count = 0
            unaccounted_total = 0
            unaccounted_total_iffy = 0
            total_in = 0
            total_out = 0
            worst_inferrer = 1
            for contract, amt in amounts.items():
                good = symbols[contract]["rate_found"]
                rate = symbols[contract]["rate"]
                try:
                    rate = float(rate)
                except:
                    good = 0
                    rate = 0
                # good, rate = coingecko_rates.lookup_rate(contract, ts)
                if do_print:
                    log("Rate lookup result", contract, symbols[contract], good, rate)
                if good == 0:
                    if amt <= 0:
                        bad_out += 1
                        bad_contract = contract
                        bad_total = -amt
                    if amt >= 0:
                        bad_in += 1
                        bad_contract = contract
                        bad_total = amt
                else:
                    worst_inferrer = min(worst_inferrer, good)
                    unaccounted_total += rate * amt
                    if amt > 0:
                        total_in += rate * amt
                    else:
                        total_out -= rate * amt

                if good < 1:
                    if amt < 0:
                        iffy_out += 1
                        iffy_contract = contract
                        iffy_total = -amt
                    if amt > 0:
                        iffy_in += 1
                        iffy_contract = contract
                        iffy_total = amt
                else:
                    unaccounted_total_iffy += rate * amt

                if good >= 1:
                    good_count += 1

            unaccounted_total = abs(unaccounted_total)
            unaccounted_total_iffy = abs(unaccounted_total_iffy)

            # if there's one really bad rate, infer that (including from iffy rates)
            # if there are no really bad rates, and one iffy rate, infer that instead
            if bad_in + bad_out == 1:
                add_rate_for = bad_contract
            elif bad_in + bad_out == 0 and iffy_in + iffy_out == 1:
                worst_inferrer = 1
                add_rate_for = iffy_contract
                bad_total = iffy_total
                unaccounted_total = unaccounted_total_iffy

            if self.hash == self.chain.hif:
                log("stats", bad_in, bad_out, iffy_in, iffy_out, add_rate_for)

            if add_rate_for:
                if do_print:
                    log(
                        "add_rate_for",
                        add_rate_for,
                        "unaccounted_total",
                        unaccounted_total,
                        "bad_total",
                        bad_total,
                        "rate",
                        unaccounted_total / bad_total,
                    )

            if add_rate_for is not None:
                try:
                    symbol = symbols[add_rate_for]["symbol"]
                    inferred_rate = unaccounted_total / bad_total
                    self.rate_inferred = symbol
                    if worst_inferrer == 1:
                        clog(self, "rate inferred 1")
                        rate_source = "inferred"
                    else:
                        rate_source = "inferred from " + str(worst_inferrer)

                    lookup_what = add_rate_for
                    if "_" in add_rate_for:
                        lookup_what = add_rate_for[: add_rate_for.index("_")]

                    if do_print:
                        log("lookup_what", lookup_what)
                    for transfer in self.lookup({"what": lookup_what}):
                        transfer.rate = inferred_rate
                        transfer.rate_found = worst_inferrer
                        transfer.rate_source = rate_source
                        if do_print:
                            log("changing rate ", self.hash, transfer)

                    coingecko_rates.add_rate(
                        self.chain.name,
                        add_rate_for,
                        self.ts,
                        inferred_rate,
                        worst_inferrer,
                        rate_source,
                    )

                except:
                    log("EXCEPTION", "contract", add_rate_for)
                    log(traceback.format_exc())
                    log(self)
                    sys.exit(0)

            # don't adjust rates for receipt tokens
            if (
                bad_in + bad_out == 0
                and add_rate_for is None
                and not skip_adjustment
                and total_out > 0
                and total_in > 0
            ):
                total_avg = (total_in + total_out) / 2.0
                try:
                    mult_adjustment_in = total_avg / total_in
                except:
                    sys.exit(1)
                mult_adjustment_out = total_avg / total_out
                adjustment_factor = abs(mult_adjustment_in - 1)
                if adjustment_factor > 0.05 or usd_present:
                    rate_fluxes = []
                    for contract, amt in amounts.items():
                        if amt == 0:
                            continue
                        good = symbols[contract]["rate_found"]
                        rate = symbols[contract]["rate"]
                        coingecko_id = symbols[contract]["coingecko_id"]
                        if contract == self.main_asset or coingecko_id == user.fiat:
                            rate_flux = 0
                        else:
                            _rate_pre_good, rate_pre, _rate_pre_source = (
                                coingecko_rates.lookup_rate(
                                    self.chain.name, contract, int(self.ts) - 3600
                                )
                            )
                            _rate_aft_good, rate_aft, _rate_aft_source = (
                                coingecko_rates.lookup_rate(
                                    self.chain.name, contract, int(self.ts) + 3600
                                )
                            )

                            if rate_pre is None or rate_aft is None or rate_pre == 0:
                                rate_flux = 1
                                log(
                                    "Couldn't find nearby rates, txid", self.txid, "hash", self.hash
                                )
                            else:
                                rate_flux = abs(rate_aft / rate_pre - 1)
                            if good < 1:
                                rate_flux += 1 - good
                        rate_fluxes.append((contract, rate_flux, rate, amt))
                    if len(rate_fluxes) > 0:
                        max_flux = max(rate_fluxes, key=lambda t: t[1])
                        if do_print:
                            log("fluxes", rate_fluxes)

                        max_flux_contract = max_flux[0]
                        max_flux_amt = max_flux[3]
                        max_flux_rate = max_flux[2]

                        if max_flux_amt > 0:
                            adjusted_rate = (
                                total_out - (total_in - max_flux_amt * max_flux_rate)
                            ) / max_flux_amt
                            if do_print:
                                log(
                                    "adjusted_rate (single 1)",
                                    max_flux_contract,
                                    adjusted_rate,
                                    total_out,
                                    total_in,
                                    max_flux_amt,
                                    max_flux_rate,
                                )
                        else:
                            max_flux_amt = -max_flux_amt
                            adjusted_rate = (
                                total_in - (total_out - max_flux_amt * max_flux_rate)
                            ) / max_flux_amt
                            if do_print:
                                log(
                                    "adjusted_rate (single 2)",
                                    max_flux_contract,
                                    adjusted_rate,
                                    total_in,
                                    total_out,
                                    max_flux_amt,
                                    max_flux_rate,
                                )

                        adjustment_factor = abs(max_flux_rate / adjusted_rate - 1)
                        for transfer in self.lookup({"what": max_flux_contract}):
                            transfer.rate = adjusted_rate
                            if not usd_present:
                                transfer.rate_source += ", adjusted by " + str(adjustment_factor)
                else:
                    for transfer in self.lookup({"from_me": True}):
                        if transfer.treatment == "sell":
                            transfer.rate *= mult_adjustment_out

                    for transfer in self.lookup({"to_me": True}):
                        if transfer.treatment == "buy":
                            transfer.rate *= mult_adjustment_in

    def type_to_typestr(self):
        type = self.type
        typestr = None
        nft = False
        if isinstance(type, Category):
            typestr = str(type)
            if type.nft:
                nft = True
        elif isinstance(type, list):
            typestr = "NOT SURE:" + str(type)
        return nft, typestr

    def to_json(self):
        ts = self.ts
        counter_parties = self.counter_parties

        nft, typestr = self.type_to_typestr()

        js = {
            "txid": self.txid,
            "chain": self.chain.name,
            "type": typestr,
            "ct_id": self.custom_type_id,
            "nft": nft,
            "hash": self.hash,
            "ts": ts,
            "classification_certainty": self.classification_certainty_level,
            "counter_parties": counter_parties,
            "function": self.function,
            "upload_id": self.upload_id,
            "changed": self.changed,
            "originator": self.originator,
            "nonce": self.nonce,
            "fiat_rate": self.fiat_rate,
            "minimized": self.minimized,
        }

        if self.custom_color_id is not None:
            js["custom_color_id"] = self.custom_color_id

        if self.custom_note is not None:
            js["custom_note"] = self.custom_note

        if self.manual:
            js["manual"] = self.manual

        if hasattr(self, "protocol_note"):
            js["protocol_note"] = self.protocol_note

        rows = {}
        for trid, transfer in self.transfers.items():
            if transfer.amount != 0:
                row = transfer.to_dict()
                rows[trid] = row

        if self.hash == self.chain.hif:
            log("json transaction", rows)

        js["rows"] = rows

        return js
