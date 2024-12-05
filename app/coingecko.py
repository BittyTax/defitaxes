# -*- coding: utf-8 -*-
import os
import pickle
import sys
import time
import traceback
from collections import defaultdict

import requests
import sortedcontainers

from .chain import Chain
from .sqlite import SQLite
from .util import log, log_error


class Coingecko:
    def __init__(self, verbose=False, use_pro=True):
        self.contracts_map = defaultdict(dict)

        self.rates = None
        self.shortcut_rates = defaultdict(dict)
        self.inferred_rates = {}
        self.shortcut_hits = 0
        self.verbose = verbose
        self.initialized = False

        self.timings = defaultdict(float)

        self.chain_mapping = {}
        self.base_ids = set()
        self.valid_ids = set()

        for chain_name, conf in Chain.CONFIG.items():
            id = conf.get("coingecko_id", chain_name.lower())
            platform = conf.get("coingecko_platform", chain_name.lower())

            self.chain_mapping[chain_name] = {"platform": platform, "id": id}
            self.base_ids.add(id)

        self.reverse_chain_mapping = {}
        for k, v in self.chain_mapping.items():
            self.reverse_chain_mapping[v["platform"]] = k

        self.custom_platform_mapping = {
            "huobi-token": {
                "usd-coin": ("0X9362BBEF4B8313A8AA9F0C9808B80577AA26B73B", "USDC"),
                "dai": ("0X3D760A45D0887DFD89A2F5385A236B29CB46ED2A", "DAI"),
            },
            "fantom": {"tether": ("0x049d68029688eabf473097a2fc38ef61633a3c7a", "USDT")},
            "oasis": {"usd-coin": ("0x94fbffe5698db6f54d6ca524dbe673a7729014be", "USDC")},
            "dogechain": {"tether": ("0xE3F5a90F9cb311505cd691a46596599aA1A0AD7D", "USDT")},
        }

        self.ignore = ["curve-fi-amdai-amusdc-amusdt"]

        self.use_pro = use_pro
        self.api_key = os.environ.get("api_key_coingecko")

    def dump(self, user):
        with open("data/users/" + user.address + "/rates", "wb") as rates_dump_file:
            pickle.dump(self, rates_dump_file)

    @classmethod
    def init_from_cache(cls, user):
        with open("data/users/" + user.address + "/rates", "rb") as f:
            C = pickle.load(f)

        log("coingecko ifc contracts_map", C.contracts_map, filename="lookups.txt")
        if len(C.contracts_map) == 0:
            return C

        inverse_contract_map = {}
        for chain_name in C.contracts_map:
            if chain_name not in inverse_contract_map:
                inverse_contract_map[chain_name] = {}
            for contract, data in C.contracts_map[chain_name].items():
                id = data["id"]
                inverse_contract_map[chain_name][id] = contract
        C.inverse_contract_map = inverse_contract_map
        return C

    @classmethod
    def find_range(cls, ts, ranges):
        for idx, (start, end) in enumerate(ranges):
            try:
                if ts < start:
                    return False, idx
            except:
                log("WTF", ts, ranges)
                sys.exit(1)
            if ts <= end:
                return True, idx

        return False, len(ranges)

    @classmethod
    def merge_ranges(cls, ranges, start, end):
        if len(ranges) == 0:
            ranges.append([start, end])
        else:
            start_in_range, start_range_idx = Coingecko.find_range(start, ranges)
            end_in_range, end_range_idx = Coingecko.find_range(end, ranges)
            log("indexes", start_range_idx, end_range_idx, filename="coingecko2.txt")
            if not start_in_range and not end_in_range:  # add new
                ranges.insert(start_range_idx, [start, end])
                del ranges[start_range_idx + 1 : end_range_idx + 1]
            elif start_in_range and not end_in_range:  # extend start's range to include the end
                ranges[start_range_idx][1] = end
                del ranges[start_range_idx + 1 : end_range_idx]
            elif not start_in_range and end_in_range:  # extend end's range to include the left
                ranges[end_range_idx][0] = start
                del ranges[start_range_idx:end_range_idx]
            elif start_range_idx != end_range_idx:  # merge two
                ranges[start_range_idx][1] = ranges[end_range_idx][1]
                del ranges[start_range_idx + 1 : end_range_idx + 1]
        return ranges

    def make_contracts_map(self):
        db = SQLite("db", do_logging=False, read_only=True)
        Q = (
            "select symbols.id, symbol, name, platform, address "
            "from symbols LEFT OUTER JOIN platforms ON symbols.id = platforms.id"
        )
        rows = db.select(Q)
        db.disconnect()
        if len(rows) == 0:
            self.download_symbols_to_db(drop=False)
            db = SQLite("db", do_logging=False, read_only=True)
            Q = (
                "select symbols.id, symbol, name, platform, address "
                "from symbols LEFT OUTER JOIN platforms ON symbols.id = platforms.id"
            )
            rows = db.select(Q)
            db.disconnect()

        valid_ids = set()
        for row in rows:
            id, symbol, _name, platform, address = row
            valid_ids.add(id)

            if platform in self.reverse_chain_mapping:
                chain_name = self.reverse_chain_mapping[platform]
                self.contracts_map[chain_name][address.lower()] = {"id": id, "symbol": symbol}

        for platform, mapping in self.custom_platform_mapping.items():
            chain_name = self.reverse_chain_mapping[platform]
            for id, tuple in mapping.items():
                self.contracts_map[chain_name][tuple[0].lower()] = {"id": id, "symbol": tuple[1]}

        for chain_name in self.chain_mapping:
            main_id = self.chain_mapping[chain_name]["id"]
            conf = Chain.CONFIG[chain_name]
            base_asset = chain_name
            if "base_asset" in conf:
                base_asset = conf["base_asset"]
            self.contracts_map[chain_name][base_asset.lower()] = {
                "id": main_id,
                "symbol": base_asset,
            }
        self.valid_ids = valid_ids

    def init_from_db_2(self, _chain_dict, needed_token_times, progress_bar=None):
        log("needed_token_times", needed_token_times, filename="coingecko2.txt")
        pb_alloc = 17.0

        db = SQLite("db", do_logging=False, read_only=True)

        id_times = {}
        for coingecko_id in needed_token_times:
            id_times[coingecko_id] = {"needed": needed_token_times[coingecko_id]}

        rq_cnt = 0
        ld_cnt = 0
        for id, id_data in id_times.items():
            if len(id_data["needed"]) == 0:
                continue
            ld_cnt += 1

        idx = 0
        if self.rates is None:
            self.rates = {}
        for id, id_data in id_times.items():

            if len(id_data["needed"]) == 0:
                continue

            if progress_bar:
                idx += 1
                progress_bar.update(
                    "Loading coingecko rates: " + str(idx) + "/" + str(ld_cnt),
                    pb_alloc * 0.3 / ld_cnt,
                )
            to_download, ranges = self.load_rates(db, id, id_data["needed"])
            id_data["ranges"] = ranges
            if len(to_download) > 0:
                id_data["to_download"] = to_download
                rq_cnt += 1

        db.disconnect()

        if rq_cnt > 0:
            idx = 0
            db = SQLite("db", do_logging=False, read_only=False)
            for id, id_data in id_times.items():
                if (
                    "to_download" not in id_data
                    or len(id_data["to_download"]) == 0
                    or id not in self.valid_ids
                ):
                    continue
                to_download = id_data["to_download"]
                ranges = id_data["ranges"]
                self.download_rates(db, id, to_download, ranges)
                if progress_bar:
                    idx += 1
                    progress_bar.update(
                        "Downloading coingecko rates [" + id + "], " + str(idx) + "/" + str(rq_cnt),
                        pb_alloc * 0.7 / rq_cnt,
                    )
            db.disconnect()
        self.initialized = True

    def load_rates(self, db, id, needed_times):
        d90 = 86400 * 90
        to_download = []
        rows = db.select(
            "SELECT start,end FROM rates_ranges WHERE id = '" + id + "' ORDER BY start ASC"
        )
        ranges = []
        for row in rows:
            ranges.append([row[0], row[1]])
        needed_times = sorted(list(needed_times))

        t = time.time()
        rows = db.select("select timestamp, rate from rates where id='" + id + "'", raw=True)
        log(
            "rate_table population time, select",
            id,
            len(rows),
            time.time() - t,
            filename="coingecko2.txt",
        )
        if id not in self.rates:
            rate_table = sortedcontainers.SortedDict()
        else:
            rate_table = self.rates[id]
        self.rates[id] = rate_table
        if len(rows):
            t = time.time()
            rate_table.update(rows)
            log(
                "rate_table population time, pop",
                id,
                len(rows),
                time.time() - t,
                filename="coingecko2.txt",
            )

        for ts in needed_times:

            in_range, _range_idx = Coingecko.find_range(ts, ranges)
            log(
                id,
                "checking time",
                ts,
                "in_range",
                in_range,
                (len(to_download) == 0 or ts > to_download[-1] + d90),
                ts < time.time() - 3600,
                filename="coingecko2.txt",
            )
            if (
                not in_range
                and (len(to_download) == 0 or ts > to_download[-1] + d90)
                and ts < time.time() - 3600
            ):
                log(id, "adding to download")
                to_download.append(ts)

        log("needed", id, needed_times, filename="coingecko2.txt")
        log("to_download", id, to_download, filename="coingecko2.txt")
        return to_download, ranges

    def download_rates(self, db, id, to_download, ranges):
        d90 = 86400 * 90

        rate_table = self.rates[id]
        for start in to_download:
            end = min(start + d90, int(time.time()))
            if self.use_pro:
                url = (
                    "https://pro-api.coingecko.com/api/v3/coins/"
                    + id
                    + "/market_chart/range?vs_currency=usd&from="
                    + str(start)
                    + "&to="
                    + str(end)
                    + "&x_cg_pro_api_key="
                    + self.api_key
                )
                sleep = 0.2
            else:
                url = (
                    "https://api.coingecko.com/api/v3/coins/"
                    + id
                    + "/market_chart/range?vs_currency=usd&from="
                    + str(start)
                    + "&to="
                    + str(end)
                )
                sleep = 3
            log("Calling", url, filename="coingecko2.txt")
            time.sleep(sleep)
            try:
                data = requests.get(url, timeout=20)
            except:
                log_error("Couldn't connect to coingecko", id, start)
                continue
            try:
                data = data.json()
            except:
                log_error("Couldn't parse coingecko response", url)
                continue
            if "prices" not in data:
                log_error("Couldn't find price data", url, "got", data)
                continue

            prices = data["prices"]

            for ts, price in prices:
                ts = int(ts / 1000)
                db.insert_kw("rates", values=[id, ts, price], ignore=True)
                rate_table[ts] = price

            # merge ranges
            log("merging ranges, current", ranges, "adding", start, end, filename="coingecko2.txt")
            ranges = Coingecko.merge_ranges(ranges, start, end)
            log("merged ranges, new", ranges, filename="coingecko2.txt")
        db.query("DELETE FROM rates_ranges WHERE id='" + id + "'")
        for range in ranges:
            db.insert_kw("rates_ranges", id=id, start=range[0], end=range[1])

        db.commit()

    def download_symbols_to_db(self, drop=False, progress_bar=None):
        pb_alloc = 2.0
        if drop:
            db = SQLite("db", do_logging=False)
            db.create_table("symbols", "id PRIMARY KEY, symbol, name", drop=drop)
            db.create_table("platforms", "id, platform, address", drop=drop)
            db.create_index("platforms_i1", "platforms", "id")
            db.create_index("platforms_i2", "platforms", "platform, address", unique=True)
            db.disconnect()

        if self.use_pro:
            url = (
                "https://pro-api.coingecko.com/api/v3/coins/list"
                "?include_platform=true&x_cg_pro_api_key=" + self.api_key
            )
        else:
            url = "https://api.coingecko.com/api/v3/coins/list?include_platform=true"
        try:
            resp = requests.get(url, timeout=10)
            data = resp.json()
        except:
            log("Failed to download coingecko symbols", traceback.format_exc())
            return
        if progress_bar:
            progress_bar.update("Loading coingecko symbols", 1)
        db = SQLite("db", do_logging=False)
        try:
            for idx, entry in enumerate(data):
                id = entry["id"]
                values = [id, entry["symbol"], entry["name"]]
                db.insert_kw("symbols", values=values, ignore=not drop)
                for platform, address in entry["platforms"].items():
                    if (
                        address is not None
                        and len(address) > 10
                        and platform is not None
                        and len(platform) > 1
                    ):
                        values = [id, platform, address]
                        db.insert_kw("platforms", values=values, ignore=not drop)

                if progress_bar:
                    progress_bar.update(
                        "Loading coingecko symbols: " + str(idx) + "/" + str(len(data)),
                        pb_alloc / len(data),
                    )
        except:
            log_error("Failed to insert coingecko symbols", traceback.format_exc())
            db.commit()
            db.disconnect()
            return
        db.commit()

        db.disconnect()

    def lookup_id(self, chain_name, contract):
        contract = contract.lower()
        try:
            return self.contracts_map[chain_name][contract]["id"]
        except:
            return None

    def add_rate(self, chain_name, contract, ts, rate, certainty, rate_source):
        coingecko_id = self.lookup_id(chain_name, contract)

        if coingecko_id is None:
            coingecko_id_or_cp = chain_name + ":" + contract
        else:
            coingecko_id_or_cp = coingecko_id
        log(
            "Adding rate",
            chain_name,
            contract,
            ts,
            rate,
            certainty,
            rate_source,
            coingecko_id_or_cp,
        )
        if self.verbose:
            log(
                "coingecko add shortcut 0",
                "add_rate",
                coingecko_id_or_cp,
                ts,
                rate,
                certainty,
                rate_source,
            )
            log("coingecko adding rate", coingecko_id_or_cp, ts, rate, certainty, rate_source)
        ts = int(ts)
        self.shortcut_rates[coingecko_id_or_cp][ts] = certainty, rate, rate_source
        if coingecko_id_or_cp not in self.inferred_rates:
            self.inferred_rates[coingecko_id_or_cp] = sortedcontainers.SortedDict()
        self.inferred_rates[coingecko_id_or_cp][ts] = rate

    def lookup_rate(self, chain_name, contract, ts):
        coingecko_id = self.lookup_id(chain_name, contract)
        if coingecko_id is None or (hasattr(self, "ignore") and coingecko_id in self.ignore):
            coingecko_id_or_cp = chain_name + ":" + contract
        else:
            coingecko_id_or_cp = coingecko_id

        rv = self.lookup_rate_by_id(coingecko_id_or_cp, ts)
        return rv

    def lookup_rate_by_id(self, coingecko_id_or_cp, ts):
        log("coingecko rate lookup", coingecko_id_or_cp, ts, filename="lookups.txt")
        found = 0
        source = "unknown"

        try:
            rv = self.shortcut_rates[coingecko_id_or_cp][ts]
            self.shortcut_hits += 1
            log("shortcut hit", rv, filename="lookups.txt")
            return rv
        except:
            pass

        good = 1
        ts = int(ts)
        # assert contract in self.contracts_map
        if coingecko_id_or_cp not in self.rates:
            log(
                "Bad rate in lookup",
                coingecko_id_or_cp,
                ts,
                "contract is not in the rates",
                filename="lookups.txt",
            )
            if coingecko_id_or_cp in self.inferred_rates:
                cp_pair = coingecko_id_or_cp
                log("Contract present in inferred rates", filename="lookups.txt")
                rates_table = self.inferred_rates[cp_pair]

                first = rates_table.keys()[0]
                last = rates_table.keys()[-1]
                source = "inferred"
                if ts < first:
                    good = 0.5
                    rate = rates_table[first]
                    if ts < first - 3600:
                        good = 0
                        source += ", before first " + str(first)
                elif ts > last:
                    rate = rates_table[last]
                    good = 0.5
                    if ts > last + 3600:
                        source += ", after last " + str(last)
                else:
                    idx = rates_table.bisect_left(ts)
                    ts_lookup = rates_table.keys()[idx - 1]
                    rate = rates_table[ts_lookup]
                    good = 0.5

                log(
                    "coingecko add shortcut 1",
                    cp_pair,
                    ts,
                    good,
                    rate,
                    source,
                    filename="lookups.txt",
                )
                self.shortcut_rates[cp_pair][ts] = (good, rate, source)
                return good, rate, source
            return 0, None, None

        coingecko_id = coingecko_id_or_cp
        rates_table = self.rates[coingecko_id]

        if ts in rates_table:
            log("Exact rate for in lookup", coingecko_id, ts, filename="lookups.txt")
            rate = rates_table[ts]
            good = 2
            source = "exact"
        else:
            try:
                times = rates_table.keys()
                first = times[0]
                last = times[-1]
            except:
                log("failed rate lookup minmax", coingecko_id, ts)
                self.shortcut_rates[coingecko_id][ts] = (0, None, "missing")
                return 0, None, None

            if ts < first:
                found = 1
                rate = rates_table[first]
                if ts < first - 3600:
                    log(
                        "Bad rate for in lookup",
                        coingecko_id,
                        ts,
                        "is smaller than first timestamp",
                        first,
                        filename="lookups.txt",
                    )
                    good = 0.3
                    source = "before first " + str(first)
                else:
                    source = "normal"

            if ts > last:
                found = 1
                rate = rates_table[last]
                if ts > last + 3600:
                    log(
                        "Bad rate for in lookup",
                        coingecko_id,
                        ts,
                        "is larger than last timestamp",
                        last,
                        filename="lookups.txt",
                    )
                    good = 0.3
                    source = "after last " + str(last)
                else:
                    source = "normal"

            if not found:
                tcore = time.time()
                idx = rates_table.bisect_left(ts)
                ts_bottom = rates_table.keys()[idx - 1]
                ts_top = rates_table.keys()[idx]
                bot_fraction = 1 - (ts - ts_bottom) / (ts_top - ts_bottom)
                top_fraction = 1 - (ts_top - ts) / (ts_top - ts_bottom)

                try:
                    rate = (
                        rates_table[ts_bottom] * bot_fraction + rates_table[ts_top] * top_fraction
                    )
                    found = True
                    source = "normal"
                    self.timings["core"] += time.time() - tcore
                except:
                    log(
                        "EXCEPTION, EXITING IN lookup_rate",
                        coingecko_id,
                        ts,
                        traceback.format_exc(),
                        filename="lookups.txt",
                    )
                    log(first, last, ts_bottom, ts_top, filename="lookups.txt")
                    return 0, None, None

        self.shortcut_rates[coingecko_id][ts] = (good, rate, source)
        log(
            "coingecko add shortcut 2", source, coingecko_id, ts, good, rate, filename="lookups.txt"
        )
        return good, rate, source
