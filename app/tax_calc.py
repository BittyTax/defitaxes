import csv
import datetime
import os
import pickle
import pprint
import re
import sys
import traceback
import zipfile

from flask import current_app

from .constants import USER_DIRNAME
from .util import decustom, log, log_error, timestamp_to_date


class Token:
    def __init__(self, id, chain_name, what, symbol, coingecko_id, nft_id):
        self.id = id
        self.symbols = {chain_name: [symbol, what]}
        self.coingecko_id = coingecko_id
        self.nft_id = nft_id

    @classmethod
    def lookup_or_create_token(
        cls, token_dict, chain_name, what, symbol, coingecko_id, nft_id=None
    ):
        if coingecko_id is not None:
            id = coingecko_id
        else:
            id = chain_name + ":" + what
        if nft_id is not None:
            id += "_" + nft_id

        if id in token_dict:
            token_dict[id].add_chain(chain_name, what, symbol)
        else:
            token_dict[id] = Token(id, chain_name, what, symbol, coingecko_id, nft_id)
        return token_dict[id]

    def add_chain(self, chain_name, what, symbol):
        self.symbols[chain_name] = [symbol, what]

    def symbol(self, chain_name=None, what_instead=False):
        if chain_name is not None:
            if what_instead:
                return self.symbols[chain_name][1]
            return self.symbols[chain_name][0]

        shortest = "X" * 10000
        for chain_name, pair in self.symbols.items():
            if pair[0] is None:
                log("No symbol in pair?", chain_name, pair, filename="aux_log.txt")
                pair[0] = ""
            if len(pair[0]) < len(shortest):
                shortest = pair[0]
                shortest_what = pair[1]
        assert len(shortest) < 10000
        if what_instead:
            return shortest_what
        return shortest

    def __eq__(self, other):
        if type(self) is type(other) and self.id is other.id:
            return True
        return False

    def __hash__(self):
        return hash(self.id)

    def to_json(self):
        log("calculator token", self)
        return {
            "what": self.symbol(what_instead=True),
            "symbols": self.symbols,
            "default_symbol": self.symbol(),
            "coingecko_id": self.coingecko_id,
            "id": self.id,
            "nft_id": self.nft_id,
        }

    def __str__(self):
        s = (
            "TOKEN: ID:"
            + str(self.id)
            + ", coingecko id:"
            + str(self.coingecko_id)
            + ", nft id:"
            + str(self.nft_id)
            + ", symbols:"
            + str(self.symbols)
        )
        return s

    def __repr__(self):
        return self.__str__()


def timestamp_to_year(ts):
    return datetime.datetime.fromtimestamp(ts).year


def rate_pick(token, timestamp, running_rates, coingecko_rates, fiat_rate):
    try:
        running_rate, running_ts = running_rates[token]
    except:
        running_rate = 0
        running_ts = timestamp
    what = token.symbol(what_instead=True)
    if (running_rate != 0 and timestamp - running_ts < 3600) or ("_" in what):
        return running_rate
    coingecko_id_or_cp = token.id

    good, coingecko_rate, _source = coingecko_rates.lookup_rate_by_id(coingecko_id_or_cp, timestamp)
    if good >= 1 or (running_rate == 0 and good > 0):
        return coingecko_rate * fiat_rate
    return running_rate


class Vault:
    def __init__(self, id, vault_gain="income", vault_loss="loss"):
        self.id = id
        self.holdings = {}
        self.usd_total = 0
        self.usd_max = 0
        self.history = []
        self.warnings = []
        self.vault_gain = vault_gain
        self.vault_loss = vault_loss

    def __str__(self):
        return "VAULT " + str(self.id) + " holdings " + str(self.holdings)

    def __repr__(self):
        return self.__str__()

    def total_usd(self, timestamp, running_rates, coingecko_rates, fiat_rate):
        total = 0
        empty = True
        bad = False
        for token, amt in self.holdings.items():
            rate = rate_pick(token, timestamp, running_rates, coingecko_rates, fiat_rate)
            if amt > 0:
                empty = False
            if rate == 0 or rate is None:
                bad = True
            total += amt * rate
        return total, empty, bad

    def deposit(self, transaction, trid, token, amount):
        if token not in self.holdings:
            self.holdings[token] = 0
        self.holdings[token] += amount
        self.history.append(
            {
                "txid": transaction["txid"],
                "trid": trid,
                "action": "deposit",
                "token": token.id,
                "amount": amount,
            }
        )

    def withdraw(
        self, transaction, trid, token, amount, running_rates, coingecko_rates, usd_fee, exit=False
    ):
        orig_amount = amount
        timestamp = transaction["ts"]
        txid = transaction["txid"]
        fiat_rate = transaction["fiat_rate"]
        log("WITHDRAW", self.id, token, amount)
        usd_total, _empty, _bad = self.total_usd(
            timestamp, running_rates, coingecko_rates, fiat_rate
        )

        self.usd_max = max(self.usd_max, usd_total)

        warning_issued = False
        if token not in self.holdings:
            warning_issued = True
            self.warnings.append(
                {
                    "txid": transaction["txid"],
                    "trid": trid,
                    "text": "Trying to withdraw "
                    + token.symbol(transaction["chain"])
                    + " which was not previously deposited into the vault",
                    "level": 5,
                }
            )
            self.holdings[token] = 0

        trades = []
        incomes = []
        expenses = []

        # first, withdraw from matching investment. If there's enough, we're done
        if self.holdings[token] >= amount:  # *0.9999:
            self.holdings[token] -= amount
            if self.holdings[token] < 0:
                self.holdings[token] = 0
            amount = 0
        else:
            amount_requested = amount
            amount_available = self.holdings[token]
            performed_conversion = False

            amount -= self.holdings[token]
            self.holdings[token] = 0

            # next, withdraw from other tokens and record swapping transactions
            holding_keys = list(self.holdings.keys())
            rate = rate_pick(token, timestamp, running_rates, coingecko_rates, fiat_rate)

            holding_keys_reordered = []
            for key_idx in range(len(holding_keys)):  # convert similar named tokens first
                other_token = holding_keys[key_idx]
                log("comp", other_token, token)
                if token.symbol() in other_token.symbol() or other_token.symbol() in token.symbol():
                    holding_keys_reordered.insert(0, other_token)
                    log("do reorder ", other_token, "in front")
                else:
                    holding_keys_reordered.append(other_token)

            log("original", holding_keys, "reordered", holding_keys_reordered)

            key_idx = 0
            while key_idx < len(holding_keys_reordered):
                usd_amt = amount * rate
                other_token = holding_keys_reordered[key_idx]
                if other_token == token:
                    key_idx += 1
                    continue
                other_rate = rate_pick(
                    other_token, timestamp, running_rates, coingecko_rates, fiat_rate
                )
                other_available = self.holdings[other_token]
                other_usd_amt = other_available * other_rate
                if other_usd_amt > 0.01:
                    if other_usd_amt > usd_amt:
                        other_sold = usd_amt / other_rate
                        if amount * rate > 0.01:
                            log(
                                self.id,
                                "WITHDRAW:CONVERSION: bought",
                                amount,
                                "of",
                                token.symbol(),
                                ", sold",
                                other_sold,
                                "of",
                                other_token.symbol(),
                            )
                            self.history.append(
                                {
                                    "txid": transaction["txid"],
                                    "trid": trid,
                                    "action": "conversion",
                                    "from": {"token": other_token.id, "amount": other_sold},
                                    "to": {"token": token.id, "amount": amount},
                                }
                            )
                            trades.append(
                                CA_transaction(timestamp, token, amount, rate, txid, trid)
                            )
                            trades.append(
                                CA_transaction(
                                    timestamp, other_token, -other_sold, other_rate, txid, trid
                                )
                            )
                            self.holdings[other_token] -= other_sold
                            performed_conversion = True
                        amount = 0
                        break
                    try:
                        amount_bought = other_usd_amt / rate
                    except:
                        log(self.id, "EXCEPTION", traceback.format_exc(), token)
                        log(transaction)
                        amount_bought = other_usd_amt
                    log(
                        self.id,
                        "WITHDRAW:CONVERSION: bought",
                        amount_bought,
                        "of",
                        token.symbol(),
                        ", sold",
                        other_available,
                        "of",
                        other_token.symbol(),
                    )
                    self.history.append(
                        {
                            "txid": transaction["txid"],
                            "trid": trid,
                            "action": "conversion",
                            "from": {"token": other_token.id, "amount": other_available},
                            "to": {"token": token.id, "amount": amount_bought},
                        }
                    )
                    trades.append(CA_transaction(timestamp, token, amount_bought, rate, txid, trid))
                    trades.append(
                        CA_transaction(
                            timestamp, other_token, -other_available, other_rate, txid, trid
                        )
                    )
                    performed_conversion = True
                    self.holdings[other_token] = 0
                    amount -= amount_bought

                key_idx += 1

            if performed_conversion and not warning_issued:
                self.warnings.append(
                    {
                        "txid": transaction["txid"],
                        "trid": trid,
                        "text": "Withdrawing "
                        + str(amount_requested)
                        + " of "
                        + token.symbol()
                        + ", but only "
                        + str(amount_available)
                        + " was deposited. Converting from other deposits.",
                        "level": 5,
                    }
                )

        # if we're out of money, the rest is profit
        self.history.append(
            {
                "txid": transaction["txid"],
                "trid": trid,
                "action": "withdraw",
                "token": token.id,
                "amount": orig_amount,
            }
        )
        if amount > 0:
            log(self.id, "WITHDRAW:NOT ENOUGH HOLDINGS")
            # may not be a property if calculator is loaded from cache
            try:
                vault_gain = self.vault_gain
            except:
                vault_gain = "income"

            if vault_gain == "income":
                incomes.append(
                    {
                        "timestamp": timestamp,
                        "text": "Income upon closing vault " + self.id,
                        "amount": amount * rate,
                        "txid": txid,
                        "trid": trid,
                        "hash": transaction["hash"],
                    }
                )
                log(self.id, "WITHDRAW:profit ", amount, "of", token)
                self.history.append(
                    {
                        "txid": transaction["txid"],
                        "trid": trid,
                        "action": "income on exit",
                        "token": token.id,
                        "amount": amount,
                    }
                )
                trades.append(CA_transaction(timestamp, token, amount, rate, txid, trid, usd_fee))

            if vault_gain == "gain":
                self.history.append(
                    {
                        "txid": transaction["txid"],
                        "trid": trid,
                        "action": "capgain on exit",
                        "token": token.id,
                        "amount": amount,
                    }
                )
                trades.append(CA_transaction(timestamp, token, amount, 0, txid, trid, usd_fee))
            close = 1

            if amount * rate > self.usd_max * 0.3:
                log(self.id, "Issuing withdrawal warning", amount * rate, self.usd_max)
                self.warnings.append(
                    {
                        "txid": transaction["txid"],
                        "trid": trid,
                        "text": "Vault income on exit is over 30% of maximum investment",
                        "level": 3,
                    }
                )
        else:
            close = 0

            remaining_usd, vault_empty, vault_bad_rate = self.total_usd(
                timestamp, running_rates, coingecko_rates, fiat_rate
            )
            log("withdrawal", self.id, remaining_usd, vault_empty, vault_bad_rate, exit)
            if (remaining_usd < 0.001 * self.usd_max and not vault_bad_rate) or vault_empty or exit:
                close = 1

        if close:
            # make sure it's the last transfer in transaction mentionining this vault
            check = False
            for transfer in transaction["ordered_transfers"]:
                if transfer["id"] == trid:
                    check = True
                    continue
                if check:
                    other_vault_id, _ = decustom(transfer["vault_id"])
                    other_treatment, _ = decustom(transfer["treatment"])

                    if other_vault_id == self.id and other_treatment in [
                        "withdraw",
                        "deposit",
                        "exit",
                    ]:
                        log(self.id, "preventing close")
                        close = 0
                        break

            if close:
                for loss_tok, loss_amt in self.holdings.items():
                    if loss_amt > 0:
                        try:
                            vault_loss = self.vault_loss
                        except:
                            vault_loss = "loss"
                        loss_rate = rate_pick(
                            loss_tok, timestamp, running_rates, coingecko_rates, fiat_rate
                        )

                        log(
                            self.id,
                            "WITHDRAW:fee loss on exit ",
                            loss_amt,
                            "of",
                            loss_tok,
                            vault_loss,
                            "loss_rate",
                            loss_rate,
                        )
                        if vault_loss == "loss":
                            self.history.append(
                                {
                                    "txid": transaction["txid"],
                                    "trid": trid,
                                    "action": "loss on exit",
                                    "token": loss_tok.id,
                                    "amount": loss_amt,
                                }
                            )
                            trades.append(
                                CA_transaction(timestamp, loss_tok, -loss_amt, 0, txid, trid)
                            )

                        if vault_loss == "sell":
                            self.history.append(
                                {
                                    "txid": transaction["txid"],
                                    "trid": trid,
                                    "action": "sell on exit",
                                    "token": loss_tok.id,
                                    "amount": loss_amt,
                                }
                            )
                            trades.append(
                                CA_transaction(
                                    timestamp, loss_tok, -loss_amt, loss_rate, txid, trid
                                )
                            )

                        if vault_loss == "expense":
                            expenses.append(
                                {
                                    "timestamp": timestamp,
                                    "text": "Business expense: exited " + self.id,
                                    "amount": loss_amt * loss_rate,
                                    "txid": txid,
                                    "trid": trid,
                                }
                            )
                            self.history.append(
                                {
                                    "txid": transaction["txid"],
                                    "trid": trid,
                                    "action": "expense on exit",
                                    "token": loss_tok.id,
                                    "amount": loss_amt,
                                }
                            )
                            trades.append(
                                CA_transaction(
                                    timestamp, loss_tok, -loss_amt, loss_rate, txid, trid
                                )
                            )

                log(self.id, "vault closed in tx ", transaction["hash"])
                self.history.append(
                    {"txid": transaction["txid"], "trid": trid, "action": "vault closed"}
                )
                self.holdings = {}
                self.usd_total = 0
                self.usd_max = 0

        return trades, incomes, expenses, close

    def to_json(self):
        holdings_conv = []
        for token, amount in self.holdings.items():
            holdings_conv.append([token.id, amount])
        js = {
            "history": self.history,
            "warnings": self.warnings,
            "holdings": holdings_conv,
            # 'holdings':self.holdings #can't do that because keys aren't strings
        }

        return js


class Loan:
    def __init__(self, id):
        self.id = id
        self.loaned = {}
        self.usd_total = 0
        self.usd_max = 0
        self.history = []
        self.warnings = []

    def __str__(self):
        return "LOAN " + self.id + " loaned " + str(self.loaned)

    def __repr__(self):
        return self.__str__()

    def total_usd(self, timestamp, running_rates, coingecko_rates, fiat_rate):
        total = 0
        empty = True
        for token, amt in self.loaned.items():
            rate = rate_pick(token, timestamp, running_rates, coingecko_rates, fiat_rate)
            if amt > 0:
                empty = False
            if rate == 0 or rate is None:
                total = None
            if total is not None:
                total += amt * rate
        return total, empty

    def borrow(self, transaction, trid, token, amount):
        txid = transaction["txid"]
        if token not in self.loaned:
            self.loaned[token] = 0
        self.loaned[token] += amount
        self.history.append(
            {"txid": txid, "trid": trid, "action": "borrow", "token": token.id, "amount": amount}
        )

    def repay(
        self, transaction, trid, token, amount, running_rates, coingecko_rates, _usd_fee, exit=False
    ):
        txid = transaction["txid"]
        fiat_rate = transaction["fiat_rate"]
        trades = []

        if token not in self.loaned:
            self.loaned[token] = 0
            self.warnings.append(
                {
                    "txid": txid,
                    "trid": trid,
                    "text": "Trying to repay "
                    + token.symbol(transaction["chain"])
                    + ", which was not previously loaned",
                    "level": 3,
                }
            )

        interest_payments = []
        self.history.append(
            {"txid": txid, "trid": trid, "action": "repay", "token": token.id, "amount": amount}
        )

        # first, repay with capital. If there's enough, we're done
        if self.loaned[token] >= amount:
            self.loaned[token] -= amount
            amount = 0
        else:
            amount -= self.loaned[token]
            self.loaned[token] = 0

        # if we're out of money, the rest is profit
        timestamp = transaction["ts"]
        rate = rate_pick(token, timestamp, running_rates, coingecko_rates, fiat_rate)

        if amount > 0:
            # print("REPAY LOAN:REPAYING MORE THAN LOANED")
            log(
                "interest",
                "timestamp",
                timestamp,
                "text",
                "Interest on loan " + self.id,
                "amount",
                amount * rate,
                "txid",
                transaction["txid"],
                "trid",
                trid,
            )
            interest_payments.append(
                {
                    "timestamp": timestamp,
                    "text": "Interest on loan " + self.id,
                    "amount": amount * rate,
                    "txid": transaction["txid"],
                    "trid": trid,
                }
            )
            rate = rate_pick(token, timestamp, running_rates, coingecko_rates, fiat_rate)
            trades.append(
                CA_transaction(timestamp, token, -amount, rate, txid, trid, queue_only=True)
            )  # loss of assets
            self.history.append(
                {
                    "txid": txid,
                    "trid": trid,
                    "action": "pay interest",
                    "token": token.id,
                    "amount": amount,
                }
            )

        if exit:  # assuming we were liquidated, acquire the rest of the loan for free
            for _lookup, amt in self.loaned.items():
                if amt != 0:
                    self.history.append(
                        {
                            "txid": txid,
                            "trid": trid,
                            "action": "buy loaned",
                            "token": token.id,
                            "amount": amt,
                            "rate": 0,
                        }
                    )
                    trades.append(CA_transaction(timestamp, token, amt, 0, txid, trid))
            self.loaned = {}

        for _what, amt in self.loaned.items():
            if amt != 0:
                break
        else:
            self.history.append({"txid": txid, "trid": trid, "action": "loan repaid"})

        return interest_payments, trades

    def to_json(self):
        holdings_conv = []
        for token, amount in self.loaned.items():
            holdings_conv.append([token.id, amount])
        js = {
            "history": self.history,
            "warnings": self.warnings,
            "loaned": holdings_conv,
        }
        return js


class CA_transaction:
    def __init__(self, timestamp, token, amount, rate, txid, trid, usd_fee=0, queue_only=False):
        if rate is None:
            rate = 0
        self.timestamp = timestamp
        self.amount = amount
        self.rate = rate
        self.queue_only = queue_only
        self.token = token
        self.basis = None
        self.sale = None
        if usd_fee is None:
            usd_fee = 0
        self.usd_fee = usd_fee

        if amount > 0:
            self.basis = amount * rate
        else:
            self.sale = -amount * rate
        self.txid = txid
        self.trid = trid
        log(
            "CA_trans",
            "txid",
            txid,
            "trid",
            trid,
            "token",
            token,
            "amount",
            amount,
            "rate",
            rate,
            "basis",
            self.basis,
            "sale",
            self.sale,
            "usd fee",
            usd_fee,
        )

    def __str__(self):
        s = str(self.timestamp) + " "
        if self.amount > 0:
            s += "acquire " + str(self.amount)
        else:
            s += "dispose " + str(-self.amount)
        s += " of " + self.token.symbol()
        if self.token.nft_id is not None:
            s += f"[{self.token.nft_id}]"
        s += " for " + str(self.rate) + " each"
        return s

    def __repr__(self):
        return self.__str__()


class Calculator:
    def __init__(self, user, coingecko_rates, mtm=False):
        self.address = user.address
        self.mtm = mtm
        self.vault_gain = "income"
        self.vault_loss = "loss"
        self.tx_costs = "sell"
        vault_gain = user.get_info("opt_vault_gain")
        if vault_gain is not None:
            self.vault_gain = vault_gain

        vault_loss = user.get_info("opt_vault_loss")
        if vault_loss is not None:
            self.vault_loss = vault_loss

        tx_costs = user.get_info("opt_tx_costs")
        if tx_costs is not None:
            self.tx_costs = tx_costs
        self.coingecko_rates = coingecko_rates

        self.hash = "0x71c7440948f9278d728a0506ebb65853bd2d4ac8f7cbff75af888c283f293e97"

        self.ca_transactions = []
        self.incomes = []
        self.interest_payments = []
        self.business_expenses = []
        self.CA_long = []
        self.CA_short = []
        self.vaults = {}
        self.loans = {}
        self.errors = {}
        self.eoy_mtm = None
        self.tokens = {}

    def process_transactions(self, transactions_js, user):
        if len(transactions_js) == 0:
            return

        fiat = user.fiat

        running_rates = {}

        vaults = self.vaults
        loans = self.loans

        try:
            tx_costs = self.tx_costs
        except:
            tx_costs = "sell"

        for _tidx, transaction in enumerate(transactions_js):
            hash = transaction["hash"]
            txid = transaction["txid"]
            fiat_rate = transaction["fiat_rate"]
            if "originator" in transaction:
                originator = transaction["originator"]
            else:
                originator = None
            timestamp = transaction["ts"]
            function = transaction["function"]

            if hash == self.hash:
                pprint.pprint(transaction)
            transfers = list(transaction["rows"].values())

            fee_amount_per_transaction = fee_rate = fee_amount = None
            fee_transfers = []
            if len(transfers) > 1:
                cnt = 0
                usd_fee_amount = 0
                for transfer in transfers:
                    treatment, _ = decustom(transfer["treatment"])
                    if treatment == "fee":
                        fee_transfers.append(transfer)
                        fee_amount = transfer["amount"]
                        try:
                            fee_rate, custom_rate = decustom(transfer["rate"])
                            fee_rate = float(fee_rate)
                            if not custom_rate:
                                fee_rate *= fiat_rate
                        except:
                            fee_rate = 0
                            log_error("Couldn't get fee rate, fee transfer", transfer)
                        usd_fee_amount += fee_amount * fee_rate
                    elif (
                        treatment in ["buy", "sell", "income"] and transfer["coingecko_id"] != fiat
                    ):
                        cnt += 1
                if cnt > 0 and fee_amount is not None:
                    fee_amount_per_transaction = usd_fee_amount / cnt
                else:
                    for transfer in fee_transfers:
                        transfer["treatment"] = "sell"

            if (
                transaction["hash"]
                == "0x7227cc0fd7353fd646be7d00d792c492dc9abd63dc7189e2e80c51dd3cd7b988"
            ):
                log("CALCULATOR FEES", fee_transfers, "CNT", cnt, fee_amount_per_transaction)

            # assume outbound transfers involving contract caller execute first
            if originator is not None:
                foreign_batch = []
                native_batch = []

                # find last outgoing transfer from the caller, insert foreign transfers after
                for t_idx, transfer in enumerate(transfers):
                    if originator not in [transfer["fr"], transfer["to"]]:
                        foreign_batch.append(transfer)
                    else:
                        native_batch.append(transfer)
                for t_idx in range(len(native_batch) - 1, -1, -1):
                    if native_batch[t_idx]["fr"] == originator:
                        transfers = native_batch[:t_idx] + foreign_batch + native_batch[t_idx:]
                        break
            transaction["ordered_transfers"] = transfers

            for transfer in transfers:
                treatment, _ = decustom(transfer["treatment"])
                coingecko_id = transfer["coingecko_id"]
                if (
                    treatment is None or treatment == "ignore" or coingecko_id == fiat
                ):  # ignore means IGNORE!
                    continue

                trid = transfer["id"]
                try:
                    contract = transfer["what"]
                except:
                    log("bad transfer", transfer)
                    sys.exit(1)
                symbol = transfer["symbol"]

                nft_id = transfer["token_nft_id"]

                token = Token.lookup_or_create_token(
                    self.tokens, transaction["chain"], contract, symbol, coingecko_id, nft_id
                )

                rate = transfer["rate"]
                if rate is None:
                    rate = 0
                rate = str(rate)
                custom_rate = False
                if "custom" in rate:
                    custom_rate = True
                    rate = rate[7:]
                if len(rate) == 0:
                    rate = 0
                else:
                    try:
                        rate = float(rate)
                        if not custom_rate:
                            rate *= fiat_rate
                        running_rates[token] = (rate, timestamp)
                    except:
                        rate = 0

                amount = transfer["amount"]

                if treatment == "loss":
                    treatment = "sell"

                if treatment in ["fee"]:
                    # these need to be later taken out of the fifo queue but ignored
                    # in cap gains calc
                    log("fee transfer in calc", transfer, "tx_costs", tx_costs, amount, rate)
                    if tx_costs == "sell":
                        self.ca_transactions.append(
                            CA_transaction(timestamp, token, -amount, rate, txid, trid)
                        )
                    elif tx_costs == "expense":
                        self.ca_transactions.append(
                            CA_transaction(timestamp, token, -amount, rate, txid, trid)
                        )
                        self.business_expenses.append(
                            {
                                "timestamp": timestamp,
                                "text": "Transaction cost",
                                "amount": amount * rate,
                                "txid": txid,
                                "trid": trid,
                            }
                        )
                    elif tx_costs == "loss":
                        self.ca_transactions.append(
                            CA_transaction(timestamp, token, -amount, 0, txid, trid)
                        )

                if treatment in ["buy", "sell"]:
                    if treatment == "sell":
                        amount = -amount
                    self.ca_transactions.append(
                        CA_transaction(
                            timestamp,
                            token,
                            amount,
                            rate,
                            txid,
                            trid,
                            usd_fee=fee_amount_per_transaction,
                        )
                    )

                if treatment in ["gift", "burn"]:
                    if treatment == "burn":
                        amount = -amount
                    self.ca_transactions.append(
                        CA_transaction(
                            timestamp,
                            token,
                            amount,
                            0,
                            txid,
                            trid,
                            usd_fee=fee_amount_per_transaction,
                        )
                    )

                try:
                    note = re.sub("<[^<]+?>", "", transaction["custom_note"])
                    if len(note) > 0:
                        explanation = " (" + note + ")"
                except:
                    explanation = ""

                if treatment == "income":
                    text = "Cryptocurrency yield farming or similar income"
                    if function == "chain-split":
                        text = "Income from a cryptocurrency chain fork"
                    elif function == "interest":
                        text = "Interest income"
                    elif function == "mining":
                        text = "Cryptocurrency mining income"
                    elif function == "airdrop":
                        text = "Cryptocurrency user incentive income"
                    elif function == "cashback":
                        text = "Cryptocurrency cashback"
                    elif function in ["royalty", "royalties"]:
                        text = "Cryptocurrency royalties"

                    self.incomes.append(
                        {
                            "timestamp": timestamp,
                            "text": text + explanation,
                            "amount": amount * rate,
                            "txid": txid,
                            "trid": trid,
                            "hash": transaction["hash"],
                        }
                    )
                    self.ca_transactions.append(
                        CA_transaction(
                            timestamp,
                            token,
                            amount,
                            rate,
                            txid,
                            trid,
                            usd_fee=fee_amount_per_transaction,
                        )
                    )

                if treatment == "interest":
                    log(
                        "interest",
                        "timestamp",
                        timestamp,
                        "text",
                        "Interest on a loan" + explanation,
                        "amount",
                        amount * rate,
                        "txid",
                        txid,
                        "trid",
                        trid,
                    )
                    self.interest_payments.append(
                        {
                            "timestamp": timestamp,
                            "text": "Interest on a loan" + explanation,
                            "amount": amount * rate,
                            "txid": txid,
                            "trid": trid,
                        }
                    )
                    self.ca_transactions.append(
                        CA_transaction(
                            timestamp,
                            token,
                            -amount,
                            rate,
                            txid,
                            trid,
                            usd_fee=fee_amount_per_transaction,
                        )
                    )

                if treatment == "expense":
                    self.business_expenses.append(
                        {
                            "timestamp": timestamp,
                            "text": "Business expense" + explanation,
                            "amount": amount * rate,
                            "txid": txid,
                            "trid": trid,
                        }
                    )
                    self.ca_transactions.append(
                        CA_transaction(
                            timestamp,
                            token,
                            -amount,
                            rate,
                            txid,
                            trid,
                            usd_fee=fee_amount_per_transaction,
                        )
                    )

                if treatment in [
                    "deposit",
                    "withdraw",
                    "borrow",
                    "repay",
                    "full_repay",
                    "exit",
                    "liquidation",
                ]:
                    vault_id, _ = decustom(transfer["vault_id"])

                    vaddr = vault_id

                if treatment in ["borrow", "repay", "full_repay", "liquidation"]:
                    if vaddr not in loans:
                        loans[vaddr] = Loan(vaddr)
                    loan = loans[vaddr]

                    if treatment == "borrow":
                        loan.borrow(transaction, trid, token, amount)

                    if treatment in ("repay", "full_repay"):
                        interest_payments, v_trades = loan.repay(
                            transaction,
                            trid,
                            token,
                            amount,
                            running_rates,
                            self.coingecko_rates,
                            fee_amount_per_transaction,
                            exit=treatment == "full_repay",
                        )
                        self.interest_payments.extend(interest_payments)
                        self.ca_transactions.extend(v_trades)

                if treatment in ["deposit", "withdraw", "exit"]:
                    if vaddr not in vaults:
                        vaults[vaddr] = Vault(vaddr, self.vault_gain, self.vault_loss)

                    vault = vaults[vaddr]
                    if treatment == "deposit":
                        vault.deposit(transaction, trid, token, amount)
                    else:
                        v_trades, v_incomes, v_expenses, _close = vault.withdraw(
                            transaction,
                            trid,
                            token,
                            amount,
                            running_rates,
                            self.coingecko_rates,
                            usd_fee=fee_amount_per_transaction,
                            exit=treatment == "exit",
                        )
                        self.ca_transactions.extend(v_trades)
                        self.incomes.extend(v_incomes)
                        log("vault expenses", v_expenses)
                        self.business_expenses.extend(v_expenses)

            del transaction["ordered_transfers"]

    def matchup(self):
        queues = {}
        modes = {}
        CA_short = []
        CA_long = []
        CA_all = []
        errors = {}
        log("processing queues")
        for _idx, ca_trans in enumerate(self.ca_transactions):
            token = ca_trans.token
            is_nft = token.nft_id is not None

            if token not in queues:
                queues[token] = []
                modes[token] = 1
            q = queues[token]
            log("trans", ca_trans, "current q", q)
            mode = modes[token]

            amount = ca_trans.amount
            txid = ca_trans.txid
            trid = ca_trans.trid
            done = False
            min_threshold = 0.000001
            while not done:
                switch = False
                if (amount > 0 and mode == 1) or (amount < 0 and mode == -1):
                    log("put current trans on q")
                    q.append(ca_trans)
                    done = True
                else:
                    amount = -amount
                    fees = ca_trans.usd_fee
                    rate = ca_trans.rate
                    pos_amount = amount * mode
                    log("subtracting from 1", "pos_amount", pos_amount, "rate", rate)
                    while pos_amount > 0 and (
                        is_nft
                        or (
                            (pos_amount * rate > min_threshold and rate != 0)
                            or (pos_amount > 0.0001 and rate == 0)
                        )
                    ):
                        log("qloop")
                        if len(q) == 0:
                            log("qcase err")
                            modes[token] = mode = -mode
                            amount = -amount
                            ca_trans.amount = amount
                            ca_trans.usd_fee = fees
                            if mode == 1:
                                ca_trans.basis = ca_trans.amount * ca_trans.rate
                            else:
                                ca_trans.sale = -ca_trans.amount * ca_trans.rate
                            switch = True
                            if mode == -1:
                                errors[txid] = {
                                    "level": 3,
                                    "error": "going short",
                                    "amount": amount,
                                    "token": token.id,
                                }
                            else:
                                errors[txid] = {
                                    "level": 5,
                                    "error": "going long",
                                    "amount": amount,
                                    "token": token.id,
                                }
                            break

                        CA_in = q[0]

                        if mode == 1:
                            if CA_in.amount > amount:
                                log("qcase 1")
                                prop_in = amount / CA_in.amount
                                basis_spent_in = CA_in.basis * prop_in
                                fees_spent_in = CA_in.usd_fee * prop_in

                                CA_in.basis -= basis_spent_in
                                CA_in.usd_fee -= fees_spent_in
                                basis = basis_spent_in + fees + fees_spent_in
                                CA_line = {
                                    "token": token.id,
                                    "amount": amount,
                                    "in_ts": CA_in.timestamp,
                                    "out_ts": ca_trans.timestamp,
                                    "basis": basis,
                                    "sale": amount * rate,
                                    "out_txid": txid,
                                    "out_trid": trid,
                                    "in_txid": CA_in.txid,
                                    "in_trid": CA_in.trid,
                                }
                                fees = 0

                                CA_in.amount -= amount
                                if CA_in.amount * CA_in.rate < min_threshold and CA_in.rate != 0:
                                    log("del first from q")
                                    del q[0]
                                amount = 0
                            else:
                                log("qcase 2")
                                prop_out = CA_in.amount / amount
                                fees_spent = fees * prop_out
                                basis = CA_in.basis + fees_spent + CA_in.usd_fee
                                fees -= fees_spent
                                CA_line = {
                                    "token": token.id,
                                    "amount": CA_in.amount,
                                    "in_ts": CA_in.timestamp,
                                    "out_ts": ca_trans.timestamp,
                                    "basis": basis,
                                    "sale": CA_in.amount * rate,
                                    "out_txid": txid,
                                    "out_trid": trid,
                                    "in_txid": CA_in.txid,
                                    "in_trid": CA_in.trid,
                                }
                                log("del first from q")
                                del q[0]
                                amount -= CA_in.amount

                        else:  # short, all amounts negative
                            if CA_in.amount < amount:
                                log("qcase 3")
                                prop_in = amount / CA_in.amount

                                sale = CA_in.sale * prop_in
                                fees_spent_in = CA_in.usd_fee * prop_in
                                basis = -amount * rate + fees + fees_spent_in
                                CA_in.usd_fee -= fees_spent_in
                                CA_in.sale -= sale

                                CA_line = {
                                    "token": token.id,
                                    "amount": -amount,
                                    "out_ts": CA_in.timestamp,
                                    "in_ts": ca_trans.timestamp,
                                    "basis": basis,
                                    "sale": sale,
                                    "in_txid": txid,
                                    "in_trid": trid,
                                    "out_txid": CA_in.txid,
                                    "out_trid": CA_in.trid,
                                }

                                CA_in.amount -= amount
                                fees = 0
                                amount = 0

                                if -CA_in.amount * CA_in.rate < min_threshold and CA_in.rate != 0:
                                    log("del first from q")
                                    del q[0]
                            else:
                                log("qcase 4")
                                prop_out = CA_in.amount / amount
                                fees_spent = fees * prop_out
                                sale = CA_in.sale
                                basis = -CA_in.amount * rate + fees_spent + CA_in.usd_fee
                                fees -= fees_spent
                                CA_line = {
                                    "token": token.id,
                                    "amount": -CA_in.amount,
                                    "out_ts": CA_in.timestamp,
                                    "in_ts": ca_trans.timestamp,
                                    "basis": basis,
                                    "sale": sale,
                                    "in_txid": txid,
                                    "in_trid": trid,
                                    "out_txid": CA_in.txid,
                                    "out_trid": CA_in.trid,
                                }
                                log("del first from q")
                                del q[0]
                                amount -= CA_in.amount

                        pos_amount = amount * mode
                        CA_line["gain"] = CA_line["sale"] - CA_line["basis"]
                        # print('cl', pos_amount, amount, CA_line)
                        CA_all.append(CA_line)
                        if abs(CA_line["out_ts"] - CA_line["in_ts"]) > 365 * 86400:
                            CA_long.append(CA_line)
                        else:
                            CA_short.append(CA_line)
                    if not switch:
                        done = True

                    if txid in errors:
                        log("errors", errors[txid])

        self.CA_long = CA_long
        self.CA_short = CA_short
        self.errors = errors

    def cache(self):
        coingecko_rates = self.coingecko_rates
        self.coingecko_rates = None
        path = os.path.join(current_app.instance_path, USER_DIRNAME)
        path = os.path.join(path, self.address)
        with open(os.path.join(path, "calculator_cache"), "wb") as cache_file:
            pickle.dump(self, cache_file)

        self.coingecko_rates = coingecko_rates

    def from_cache(self):
        path = os.path.join(current_app.instance_path, USER_DIRNAME)
        path = os.path.join(path, self.address)
        with open(os.path.join(path, "calculator_cache"), "rb") as f:
            C = pickle.load(f)

        self.CA_long = C.CA_long
        self.CA_short = C.CA_short
        self.errors = C.errors
        self.eoy_mtm = C.eoy_mtm
        self.ca_transactions = C.ca_transactions
        self.incomes = C.incomes
        self.interest_payments = C.interest_payments
        try:
            self.business_expenses = C.business_expenses
        except:
            self.business_expenses = []

        try:
            self.vault_gain = C.vault_gain
        except:
            self.vault_gain = "income"

        try:
            self.vault_loss = C.vault_loss
        except:
            self.vault_loss = "loss"

        try:
            self.tx_costs = C.tx_costs
        except:
            self.tx_costs = "sell"

        self.mtm = C.mtm
        self.vaults = C.vaults
        self.loans = C.loans
        self.tokens = C.tokens

    def CA_to_form(self, CA, year, format=None):
        log("ca_to_form", year, filename="ca_to_form.txt")

        rows = []
        total_proceeds = 0
        total_cost = 0
        for ca_line in CA:
            if timestamp_to_year(ca_line["out_ts"]) == year:
                # symbol = str(ca_line['symbol'].encode("utf-8"))[2:-1]
                symbol = str(self.tokens[ca_line["token"]].symbol().encode("utf-8"))[2:-1]
                if len(symbol) == 0:
                    symbol = "Unknown token: " + self.tokens[ca_line["token"]].symbol(
                        what_instead=True
                    )
                if format is None:
                    row = [
                        str(ca_line["amount"]) + " units of " + symbol,
                        timestamp_to_date(ca_line["in_ts"]),
                        timestamp_to_date(ca_line["out_ts"]),
                        round(ca_line["sale"], 2),
                        round(ca_line["basis"], 2),
                        round(ca_line["gain"], 2),
                    ]
                elif format == "turbotax":
                    row = [
                        symbol,
                        timestamp_to_date(ca_line["in_ts"]),
                        round(ca_line["basis"], 2),
                        timestamp_to_date(ca_line["out_ts"]),
                        round(ca_line["sale"], 2),
                    ]
                rows.append(row)
                total_proceeds += ca_line["sale"]
                total_cost += ca_line["basis"]
        log(
            "ca_to_form",
            "total_proceeds",
            total_proceeds,
            "total_cost",
            total_cost,
            filename="ca_to_form.txt",
        )
        return rows, round(total_proceeds), round(total_cost)

    def make_turbotax(self, year):
        year = int(year)
        path = os.path.join(current_app.instance_path, USER_DIRNAME)
        path = os.path.join(path, self.address)

        form_8949_short, _short_total_proceeds, _short_total_cost = self.CA_to_form(
            self.CA_short, year, format="turbotax"
        )
        form_8949_long, _long_total_proceeds, _long_total_cost = self.CA_to_form(
            self.CA_long, year, format="turbotax"
        )

        all_rows = []
        if form_8949_short:
            all_rows += form_8949_short
        if form_8949_long:
            all_rows += form_8949_long

        if len(all_rows) < 4000:  # turbotax limit
            with open(
                os.path.join(path, f"turbotax_8949_{year}.csv"), "w", encoding="utf-8"
            ) as form_file:
                writer = csv.writer(form_file)
                writer.writerow(
                    ["Currency Name", "Purchase Date", "Cost Basis", "Date Sold", "Proceeds"]
                )
                writer.writerows(all_rows)
            return 0

        batch_size = 3999
        batch_cnt = len(all_rows) // batch_size + 1
        offset = 0
        file_list = []
        for batch_idx in range(batch_cnt):
            file_name = f"turbotax_8949_{year}_batch_{batch_idx + 1}.csv"
            file_list.append(file_name)
            with open(os.path.join(path, file_name), "w", encoding="utf-8") as form_file:
                writer = csv.writer(form_file)
                writer.writerow(
                    ["Currency Name", "Purchase Date", "Cost Basis", "Date Sold", "Proceeds"]
                )
                writer.writerows(all_rows[offset : offset + batch_size])

            offset += batch_size

        compression = zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(os.path.join(path, f"turbotax_8949_{year}.zip"), mode="w") as zf:
            for filename in file_list:
                zf.write(os.path.join(path, filename), arcname=filename, compress_type=compression)
        return 1

    def make_forms(self, year):
        year = int(year)
        path = os.path.join(current_app.instance_path, USER_DIRNAME)
        path = os.path.join(path, self.address)

        form_8949_short, short_total_proceeds, short_total_cost = self.CA_to_form(
            self.CA_short, year
        )
        form_8949_long, long_total_proceeds, long_total_cost = self.CA_to_form(self.CA_long, year)

        file_list = []

        if not self.mtm:
            if len(form_8949_short) > 0 or len(form_8949_long) > 0:
                with open(
                    os.path.join(path, "form_1040_schedule_D.txt"), "w", encoding="utf-8"
                ) as form_file:
                    if short_total_proceeds != 0:
                        gain = short_total_proceeds - short_total_cost
                        form_file.write("\nRow 3, column (d): " + str(short_total_proceeds))
                        form_file.write("\nRow 3, column (e): " + str(short_total_cost))
                        form_file.write("\nRow 3, column (h): " + str(gain))
                        form_file.write("\nRow 7, column (h): " + str(gain))

                    if long_total_proceeds != 0:
                        gain = long_total_proceeds - long_total_cost
                        form_file.write("\nRow 10, column (d): " + str(long_total_proceeds))
                        form_file.write("\nRow 10, column (e): " + str(long_total_cost))
                        form_file.write("\nRow 10, column (h): " + str(gain))
                        form_file.write("\nRow 15, column (h): " + str(gain))

                    form_file.write("\n\nYou will need to complete the rest of the form yourself")

                file_list.append("form_1040_schedule_D.txt")
        else:
            if len(form_8949_short) > 0:
                with open(
                    os.path.join(path, "form_4797_part_2.csv"), "w", encoding="utf-8"
                ) as form_file:
                    file_list.append("form_4797_part_2.csv")
                    writer = csv.writer(form_file)
                    writer.writerow(
                        [
                            "Description of property",
                            "Date acquired",
                            "Date sold or disposed of",
                            "Proceeds/Gross sales price",
                            "Cost basis",
                            "Gain or loss",
                        ]
                    )
                    rows = [
                        [
                            "Trader - see attached",
                            "",
                            "",
                            short_total_proceeds,
                            short_total_cost,
                            short_total_proceeds - short_total_cost,
                        ]
                    ]
                    writer.writerows(rows)

                if self.eoy_mtm is not None:
                    with open(
                        os.path.join(path, f"mark_to_market_eoy_{year - 1}_holdings.txt"),
                        "w",
                        encoding="utf-8",
                    ) as form_file:
                        file_list.append("mark_to_market_eoy_" + str(year - 1) + "_holdings.txt")

                        writer = csv.writer(form_file)
                        writer.writerow(["Description of property"])
                        rows = []
                        for token, amount in self.eoy_mtm.items():
                            contract = token.symbol(what_instead=True)
                            if "_" in contract:
                                contract, _nft_id = contract.split("_")
                            desc = (
                                str(amount) + " units of " + token.symbol() + " (" + contract + ")"
                            )
                            rows.append([desc])
                        writer.writerows(rows)

        if len(form_8949_short) > 0:
            if self.mtm:
                filename = "form_4797_attachment.csv"
            else:
                filename = "form_8949_part_1.csv"

            with open(os.path.join(path, filename), "w", newline="", encoding="utf-8") as form_file:
                file_list.append(filename)
                writer = csv.writer(form_file)
                writer.writerow(
                    [
                        "Description of property",
                        "Date acquired",
                        "Date sold or disposed of",
                        "Proceeds/Gross sales price",
                        "Cost basis",
                        "Gain or loss",
                    ]
                )
                writer.writerows(form_8949_short)

        if not self.mtm:
            if len(form_8949_long) > 0:
                with open(
                    os.path.join(path, "form_8949_part_2.csv"), "w", newline="", encoding="utf-8"
                ) as form_file:
                    file_list.append("form_8949_part_2.csv")
                    writer = csv.writer(form_file)
                    writer.writerow(
                        [
                            "Description of property",
                            "Date acquired",
                            "Date sold or disposed of",
                            "Proceeds",
                            "Cost basis",
                            "Gain or loss",
                        ]
                    )
                    writer.writerows(form_8949_long)

        log("incomes", self.incomes)
        if len(self.incomes) > 0:
            with open(
                os.path.join(path, "income_list.csv"), "w", newline="", encoding="utf-8"
            ) as income_list_file:
                writer = csv.writer(income_list_file)
                writer.writerow(
                    [
                        (
                            "This file is for your records. "
                            "It's a list of all transactions that produced income."
                        ),
                        "",
                        "",
                        "",
                    ]
                )
                writer.writerow(["Timestamp", "Transaction hash", "Description", "Income amount"])

                income_types = {}
                for income in self.incomes:
                    if timestamp_to_year(income["timestamp"]) == year:
                        income_list_row = [
                            timestamp_to_date(income["timestamp"], and_time=True),
                            income["hash"],
                            income["text"],
                            income["amount"],
                        ]
                        writer.writerow(income_list_row)

                        income_type = income["text"]
                        if income_type not in income_types:
                            income_types[income_type] = 0
                        income_types[income_type] += income["amount"]

            file_list.append("income_list.csv")

            if len(income_types) > 0:
                with open(
                    os.path.join(path, "form_1040_schedule_1.txt"), "w", encoding="utf-8"
                ) as form_file:
                    file_list.append("form_1040_schedule_1.txt")
                    form_file.write(
                        "\nOnly use this if you DON'T have a registered crypto business. "
                        "Otherwise use form_1040_schedule_C.txt"
                    )
                    total = 0
                    for type, amount in income_types.items():
                        if amount > 0.5:
                            form_file.write(
                                "\nRow 8 income type: " + type + ", amount: " + str(round(amount))
                            )
                        total += amount
                    form_file.write("\nRow 8 total: " + str(round(total)))

        log("expenses", self.business_expenses)
        if self.business_expenses:
            expense_types = {}
            for expense in self.business_expenses:
                if timestamp_to_year(expense["timestamp"]) == year:
                    expense_type = expense["text"]
                    if expense_type not in expense_types:
                        expense_types[expense_type] = 0
                    expense_types[expense_type] += expense["amount"]

            if len(expense_types) > 0:
                with open(
                    os.path.join(path, "form_1040_schedule_C.txt"), "w", encoding="utf-8"
                ) as schedule_C:
                    file_list.append("form_1040_schedule_C.txt")
                    total = 0
                    for type, amount in expense_types.items():
                        if amount > 0.5:
                            schedule_C.write(
                                "\nPart V row: " + type + ", amount: " + str(round(amount))
                            )
                        total += amount
                    schedule_C.write("\nRows 27a, 48: " + str(round(total)))
                    schedule_C.write(
                        "\n\nYou will need to complete the rest of the form yourself. "
                        "Note that you should only file this if cryptocurrency trading is a "
                        "substantial part of your daily routine, or if you have a registered "
                        "business. You may wish to consult with a tax professional about this. "
                        "You may owe additional self-employment taxes."
                    )

        if self.interest_payments:
            with open(os.path.join(path, "form_4952.txt"), "w", encoding="utf-8") as form_file:
                file_list.append("form_4952.txt")
                total = 0
                form_file.write(
                    "\nWe strongly recommend consulting with a tax professional about "
                    "deducting loan interest\n"
                )
                for entry in self.interest_payments:
                    if timestamp_to_year(entry["timestamp"]) == year:
                        total += entry["amount"]
                form_file.write("\nLine 1: " + str(round(total)))
                form_file.write("\n\nYou will need to complete the rest of the form yourself")

        compression = zipfile.ZIP_DEFLATED
        with zipfile.ZipFile(os.path.join(path, f"tax_forms_{year}.zip"), mode="w") as zf:
            for filename in file_list:
                zf.write(os.path.join(path, filename), arcname=filename, compress_type=compression)

    def vaults_json(self):
        js = {}
        for vault_id, vault in self.vaults.items():
            js[vault_id] = vault.to_json()
        return js

    def loans_json(self):
        js = {}
        for loan_id, loan in self.loans.items():
            js[loan_id] = loan.to_json()
        return js

    def tokens_json(self):
        js = {}
        for token_id, token in self.tokens.items():
            js[token_id] = token.to_json()
        return js
