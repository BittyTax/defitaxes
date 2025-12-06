import os
import pickle
import sqlite3
import sys
import threading
import time
from collections import defaultdict
from enum import Enum
from http import HTTPMethod, HTTPStatus
from typing import TYPE_CHECKING, Any, Dict, List, NotRequired, Optional, Tuple, TypedDict, Union

import requests
import sortedcontainers
from flask import current_app

from .chain import Chain
from .constants import USER_DIRNAME
from .sqlite import SQLite
from .util import prettyp

if TYPE_CHECKING:
    from .user import User


class CoinGeckoApiFailureNoResponse(Exception):
    pass


class CoinGeckoApiFailureBadResponse(Exception):
    pass


class CoinGeckoCoinStatus(Enum):
    ACTIVE = 0
    INACTIVE = 1
    DELISTED = 2


class CgIdTimesData(TypedDict):
    needed: List[int]
    ranges: NotRequired[List[List[int]]]
    to_download: NotRequired[List[int]]


class CoinGecko:
    IGNORE = ["curve-fi-amdai-amusdc-amusdt"]

    CUSTOM_PLATFORM_MAPPING = {
        "huobi-token": {
            "usd-coin": ("0X9362BBEF4B8313A8AA9F0C9808B80577AA26B73B", "USDC"),
            "dai": ("0X3D760A45D0887DFD89A2F5385A236B29CB46ED2A", "DAI"),
        },
        "fantom": {"tether": ("0x049d68029688eabf473097a2fc38ef61633a3c7a", "USDT")},
        "oasis": {"usd-coin": ("0x94fbffe5698db6f54d6ca524dbe673a7729014be", "USDC")},
        "dogechain": {"tether": ("0xE3F5a90F9cb311505cd691a46596599aA1A0AD7D", "USDT")},
    }

    def __init__(self) -> None:
        self.contracts_map: defaultdict[str, dict] = defaultdict(dict)

        self.rates: Dict[str, Any] = {}
        self.shortcut_rates: defaultdict[str, dict] = defaultdict(dict)
        self.inferred_rates: dict[str, sortedcontainers.SortedDict] = {}
        self.initialized = False

        self.chain_mapping = {}
        self.base_ids = set()
        self.valid_ids: set[str] = set()

        for chain_name, conf in Chain.CONFIG.items():
            cg_id = conf.get("coingecko_id", chain_name.lower())
            platform = conf.get("coingecko_platform", chain_name.lower())

            self.chain_mapping[chain_name] = {"platform": platform, "id": cg_id}
            self.base_ids.add(cg_id)

        self.reverse_chain_mapping = {}
        for k, v in self.chain_mapping.items():
            self.reverse_chain_mapping[v["platform"]] = k

        self.api = CoinGeckoApi()

    def dump(self, user: "User") -> None:
        path = os.path.join(current_app.instance_path, USER_DIRNAME)
        path = os.path.join(path, user.address)
        with open(os.path.join(path, "rates"), "wb") as f:
            pickle.dump(self, f)

    def __getstate__(self) -> dict:
        state = self.__dict__.copy()
        # Remove the api attribute from pickling
        if "api" in state:
            state["api"] = None
        return state

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)
        # Restore the API when unpickling
        self.api = CoinGeckoApi()

    @classmethod
    def init_from_cache(cls, user: "User") -> "CoinGecko":
        path = os.path.join(current_app.instance_path, USER_DIRNAME)
        path = os.path.join(path, user.address)
        with open(os.path.join(path, "rates"), "rb") as f:
            cg = pickle.load(f)

        current_app.logger.debug("contacts_map %s", prettyp(cg.contracts_map))

        if cg.contracts_map:
            inverse_contract_map: dict[str, dict[str, str]] = {}
            for chain_name in cg.contracts_map:
                if chain_name not in inverse_contract_map:
                    inverse_contract_map[chain_name] = {}
                for contract, data in cg.contracts_map[chain_name].items():
                    cg_id = data["id"]
                    inverse_contract_map[chain_name][cg_id] = contract
            cg.inverse_contract_map = inverse_contract_map
        return cg

    @classmethod
    def _find_range(cls, ts: int, ranges: List[List[int]]) -> Tuple[bool, int]:
        for idx, (start, end) in enumerate(ranges):
            try:
                if ts < start:
                    return False, idx
            except (TypeError, ValueError) as e:
                current_app.logger.error(
                    "Error in _find_range: %s %s %s", str(e), ts, prettyp(ranges)
                )
                sys.exit(1)
            if ts <= end:
                return True, idx

        return False, len(ranges)

    @classmethod
    def _merge_ranges(cls, ranges: List[List[int]], start: int, end: int) -> List[List[int]]:
        if len(ranges) == 0:
            ranges.append([start, end])
        else:
            start_in_range, start_range_idx = CoinGecko._find_range(start, ranges)
            end_in_range, end_range_idx = CoinGecko._find_range(end, ranges)
            current_app.logger.debug(
                "indexes start_idx=%s end_idx=%s", start_range_idx, end_range_idx
            )

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

    def make_contracts_map(self) -> None:
        db = SQLite("db", read_only=True)
        rows = db.select(
            "SELECT symbols.id, symbol, principal, platform, address "
            "FROM symbols LEFT OUTER JOIN platforms ON symbols.id = platforms.id"
        )
        db.disconnect()

        valid_ids = set()
        for row in rows:
            cg_id, symbol, principal, platform, address = row
            valid_ids.add(cg_id)

            if platform in self.reverse_chain_mapping:
                chain_name = self.reverse_chain_mapping[platform]
                self.contracts_map[chain_name][address.lower()] = {
                    "id": cg_id,
                    "symbol": symbol,
                    "principal": bool(principal),
                }

        for platform, mapping in CoinGecko.CUSTOM_PLATFORM_MAPPING.items():
            chain_name = self.reverse_chain_mapping[platform]
            for cg_id, (address, symbol) in mapping.items():
                self.contracts_map[chain_name][address.lower()] = {
                    "id": cg_id,
                    "symbol": symbol,
                    "principal": True,
                }

        for chain_name, chain_data in self.chain_mapping.items():
            main_id = chain_data["id"]
            conf = Chain.CONFIG[chain_name]
            base_asset = conf.get("base_asset", chain_name)
            self.contracts_map[chain_name][base_asset.lower()] = {
                "id": main_id,
                "symbol": base_asset,
                "principal": True,
            }
        self.valid_ids = valid_ids

    def init_from_db_2(
        self,
        needed_token_times: Dict[str, List[int]],
        progress_bar: Optional[Any] = None,
    ) -> None:
        current_app.logger.debug("needed_token_times: %s", prettyp(needed_token_times))
        pb_alloc = 17.0

        db = SQLite("db", read_only=True)

        id_times: Dict[str, CgIdTimesData] = {}
        for coingecko_id in needed_token_times:
            id_times[coingecko_id] = {"needed": needed_token_times[coingecko_id]}

        rq_cnt = 0
        ld_cnt = 0
        for cg_id, id_data in id_times.items():
            if len(id_data["needed"]) == 0:
                continue
            ld_cnt += 1

        idx = 0
        for cg_id, id_data in id_times.items():
            if len(id_data["needed"]) == 0:
                continue

            if progress_bar:
                idx += 1
                progress_bar.update(
                    f"Loading coingecko rates: {idx}/{ld_cnt}",
                    pb_alloc * 0.3 / ld_cnt,
                )
            to_download, ranges = self.load_rates(db, cg_id, id_data["needed"])
            id_data["ranges"] = ranges

            if len(to_download) > 0:
                id_data["to_download"] = to_download
                rq_cnt += 1

        db.disconnect()

        if rq_cnt > 0:
            idx = 0
            db = SQLite("db", read_only=False)
            for cg_id, id_data in id_times.items():
                if (
                    "to_download" not in id_data
                    or len(id_data["to_download"]) == 0
                    or cg_id not in self.valid_ids
                ):
                    continue

                to_download = id_data["to_download"]
                ranges = id_data["ranges"]
                self.download_rates(db, cg_id, to_download, ranges)
                if progress_bar:
                    idx += 1
                    progress_bar.update(
                        f"Downloading coingecko rates [{cg_id}], {idx}/{rq_cnt}",
                        pb_alloc * 0.7 / rq_cnt,
                    )

            db.disconnect()
        self.initialized = True

    def load_rates(
        self, db: SQLite, cg_id: str, needed_times: List[int]
    ) -> Tuple[List[int], List[List[int]]]:
        d90 = 86400 * 90
        to_download: List[int] = []
        rows = db.select(
            f"SELECT start, end FROM rates_ranges WHERE id = '{cg_id}' ORDER BY start ASC"
        )
        ranges = []
        for row in rows:
            ranges.append([row[0], row[1]])
        needed_times = sorted(list(needed_times))

        t = time.time()
        rows = db.select(f"SELECT timestamp, rate FROM rates WHERE id='{cg_id}'", raw=True)
        current_app.logger.debug(
            "rate_table population time, select cg_id=%s rows=%d time=%s",
            cg_id,
            len(rows),
            time.time() - t,
        )

        if cg_id not in self.rates:
            rate_table = sortedcontainers.SortedDict()
        else:
            rate_table = self.rates[cg_id]
        self.rates[cg_id] = rate_table
        if len(rows):
            t = time.time()
            rate_table.update(rows)
            current_app.logger.debug(
                "rate_table population time, pop cg_id=%s rows=%d time=%s",
                cg_id,
                len(rows),
                time.time() - t,
            )

        for ts in needed_times:
            in_range, _range_idx = CoinGecko._find_range(ts, ranges)
            current_app.logger.debug(
                "checking time cg_id=%s ts=%s in_range=%s %s %s",
                cg_id,
                ts,
                in_range,
                (len(to_download) == 0 or ts > to_download[-1] + d90),
                ts < time.time() - 3600,
            )
            if (
                not in_range
                and (len(to_download) == 0 or ts > to_download[-1] + d90)
                and ts < time.time() - 3600
            ):
                current_app.logger.debug("adding to download cg_id=%s ts=%s", cg_id, ts)
                to_download.append(ts)

        current_app.logger.debug("needed_times for cg_id=%s: %s", cg_id, prettyp(needed_times))
        current_app.logger.debug("to_download for cg_id=%s: %s", cg_id, prettyp(to_download))
        return to_download, ranges

    def download_rates(
        self, db: SQLite, cg_id: str, to_download: List[int], ranges: List[List[int]]
    ) -> None:
        d90 = 86400 * 90

        rate_table = self.rates[cg_id]
        for start in to_download:
            end = min(start + d90, int(time.time()))
            try:
                data = self.api.coins_market_chart(cg_id, start, end)
            except CoinGeckoApiFailureNoResponse:
                current_app.logger.error(
                    "No response from coingecko for cg_id=%s start=%s end=%s", cg_id, start, end
                )
                continue
            except CoinGeckoApiFailureBadResponse:
                current_app.logger.error(
                    "Bad response from coingecko for cg_id=%s start=%s end=%s", cg_id, start, end
                )
                continue

            if "prices" not in data:
                current_app.logger.error(
                    "No price data from coingecko for cg_id=%s data=%s", cg_id, prettyp(data)
                )
                continue

            prices = data["prices"]

            for ts, price in prices:
                ts = int(ts / 1000)
                db.insert_kw("rates", values=[cg_id, ts, price], ignore=True)
                rate_table[ts] = price

            # merge ranges
            current_app.logger.debug(
                "merging ranges, current cg_id=%s: %s adding start=%s end=%s",
                cg_id,
                prettyp(ranges),
                start,
                end,
            )
            ranges = CoinGecko._merge_ranges(ranges, start, end)
            current_app.logger.debug("merged ranges, new cg_id=%s: %s", cg_id, prettyp(ranges))
        db.query("DELETE FROM rates_ranges WHERE id='" + cg_id + "'")
        for ts_range in ranges:
            db.insert_kw("rates_ranges", id=cg_id, start=ts_range[0], end=ts_range[1])

        db.commit()

    def create_tables(self, drop: bool = False) -> None:
        db = SQLite("db")
        try:
            db.execute("BEGIN TRANSACTION")

            if drop:
                db.execute("DROP TABLE IF EXISTS symbols")

            db.execute(
                "CREATE TABLE IF NOT EXISTS symbols (id PRIMARY KEY, symbol TEXT, name TEXT, "
                "stablecoin INTEGER, wrapped_token INTEGER, bridged_token INTEGER, "
                "market_cap INTEGER, principal INTEGER, status INTEGER)"
            )

            # Create platforms table with IF NOT EXISTS when not dropping
            if drop:
                db.execute("DROP TABLE IF EXISTS platforms")

            db.execute(
                "CREATE TABLE IF NOT EXISTS platforms (id TEXT, platform TEXT, address TEXT)"
            )

            # Create indexes with IF NOT EXISTS when not dropping
            if drop:
                db.execute("DROP INDEX IF EXISTS platforms_i1")
                db.execute("DROP INDEX IF EXISTS platforms_i2")

            db.execute("CREATE INDEX IF NOT EXISTS platforms_i1 ON platforms (id)")
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS platforms_i2 ON platforms (platform, address)"
            )

            db.execute("COMMIT")
        except sqlite3.Error as e:
            db.execute("ROLLBACK")
            raise e
        finally:
            db.disconnect()

    def download_symbols(self) -> None:
        db = SQLite("db")
        try:
            # Get active coins
            coins = self.api.coins_list(CoinGeckoCoinStatus.ACTIVE)
            if current_app.config["COINGECKO_PRO"]:
                # Add inactive coins if using Pro API
                coins += self.api.coins_list(CoinGeckoCoinStatus.INACTIVE)

            # Get market cap data for each coin
            id_to_market_cap = {
                coin["id"]: coin["market_cap"]
                for coin in self.api.coins_markets()
                if "id" in coin and "market_cap" in coin and coin["market_cap"]
            }

            # Get list of stablecoins, bridged and wrapped tokens
            stablecoins = [coin["id"] for coin in self.api.coins_markets("stablecoins")]
            wrapped_tokens = [coin["id"] for coin in self.api.coins_markets("wrapped-tokens")]
            bridged_tokens = [coin["id"] for coin in self.api.coins_markets("bridged-tokens")]
            highest_caps = self._find_highest_market_cap(coins, id_to_market_cap)

            db.execute("BEGIN TRANSACTION")

            # Delete all existing platform entries
            db.execute("DELETE FROM platforms")

            # First mark all existing symbols as delisted (status=2) and reset principal flag
            db.execute(
                "UPDATE symbols SET principal = 0, status = ?",
                [CoinGeckoCoinStatus.DELISTED.value],
            )

            # Process and insert all coins
            for coin in coins:
                cg_id = coin["id"]
                is_stablecoin = 1 if cg_id in stablecoins else 0
                is_wrapped_token = 1 if cg_id in wrapped_tokens else 0
                is_bridged_token = 1 if cg_id in bridged_tokens else 0
                is_principal = (
                    1
                    if cg_id in stablecoins
                    or cg_id in wrapped_tokens
                    or cg_id in bridged_tokens
                    or cg_id in highest_caps
                    else 0
                )

                db.execute(
                    "INSERT OR REPLACE INTO symbols (id, symbol, name, stablecoin, wrapped_token, "
                    "bridged_token, market_cap, principal, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        cg_id,
                        coin["symbol"],
                        coin["name"],
                        is_stablecoin,
                        is_wrapped_token,
                        is_bridged_token,
                        id_to_market_cap.get(cg_id, 0),
                        is_principal,
                        coin["status"],
                    ],
                )

                platform_rows = []
                for platform, address in coin["platforms"].items():
                    if platform and address:
                        platform_rows.append((cg_id, platform, address))

                if platform_rows:
                    db.execute_many(
                        "INSERT INTO platforms (id, platform, address) VALUES (?, ?, ?)",
                        platform_rows,
                    )

            db.execute("COMMIT")

            # Log statistics
            result = db.select(
                f"SELECT COUNT(*) FROM symbols WHERE status = {CoinGeckoCoinStatus.DELISTED.value}"
            )
            delisted_count = result[0][0] if result else 0
            if delisted_count > 0:
                current_app.logger.warning(
                    f"Found {delisted_count:,} delisted coins from CoinGecko"
                )

            result = db.select("SELECT COUNT(*) FROM symbols WHERE principal = 1")
            principal_count = result[0][0] if result else 0
            current_app.logger.info(
                f"Updated {len(coins):,} coins with {principal_count:,} principals from CoinGecko"
            )
        except (CoinGeckoApiFailureNoResponse, CoinGeckoApiFailureBadResponse):
            # Roll back if there was an API issue
            db.query("ROLLBACK")
            current_app.logger.error("Failed to download CoinGecko symbols")
        except sqlite3.Error as e:
            # Roll back on specific database or value errors
            db.query("ROLLBACK")
            current_app.logger.error("Failed to insert CoinGecko symbols, error=%s", str(e))
        finally:
            db.disconnect()

    def _find_highest_market_cap(
        self, coins: List[Any], id_to_market_cap: Dict[str, Union[int, float]]
    ) -> List[str]:
        symbols_map: Dict[str, List[Dict[str, Any]]] = {}
        for coin in coins:
            symbol = coin["symbol"].lower()
            cg_id = coin["id"]

            if symbol not in symbols_map:
                symbols_map[symbol] = []

            symbols_map[symbol].append({"id": cg_id, "market_cap": id_to_market_cap.get(cg_id, 0)})

        highest_caps = []
        for symbol, symbol_coins in symbols_map.items():
            highest_cap = 0
            cg_id = None

            for coin in symbol_coins:
                if coin["market_cap"] > highest_cap:
                    highest_cap = coin["market_cap"]
                    cg_id = coin["id"]

            if cg_id and highest_cap > 0:
                highest_caps.append(cg_id)

        return highest_caps

    def lookup_id(self, chain_name: str, contract: str) -> Optional[str]:
        contract = contract.lower()
        try:
            return self.contracts_map[chain_name][contract]["id"]
        except KeyError:
            return None

    def lookup_principal(self, chain_name: str, contract: str) -> bool:
        contract = contract.lower()
        try:
            return self.contracts_map[chain_name][contract]["principal"]
        except KeyError:
            return False

    def add_rate(
        self,
        chain_name: str,
        contract: str,
        ts: int,
        rate: float,
        certainty: float,
        rate_source: str,
    ) -> None:
        coingecko_id = self.lookup_id(chain_name, contract)

        if coingecko_id is None:
            coingecko_id_or_cp = chain_name + ":" + contract
        else:
            coingecko_id_or_cp = coingecko_id

        current_app.logger.info(
            "Adding rate %s %s %s %s %s %s %s",
            chain_name,
            contract,
            ts,
            rate,
            certainty,
            rate_source,
            coingecko_id_or_cp,
        )

        ts = int(ts)
        self.shortcut_rates[coingecko_id_or_cp][ts] = certainty, rate, rate_source
        if coingecko_id_or_cp not in self.inferred_rates:
            self.inferred_rates[coingecko_id_or_cp] = sortedcontainers.SortedDict()
        self.inferred_rates[coingecko_id_or_cp][ts] = rate

    def lookup_rate(
        self, chain_name: str, contract: str, ts: int
    ) -> Tuple[float, Optional[float], Optional[str]]:
        coingecko_id = self.lookup_id(chain_name, contract)
        if coingecko_id is None or coingecko_id in CoinGecko.IGNORE:
            coingecko_id_or_cp = chain_name + ":" + contract
        else:
            coingecko_id_or_cp = coingecko_id

        rv = self.lookup_rate_by_id(coingecko_id_or_cp, ts)
        return rv

    def lookup_rate_by_id(
        self, coingecko_id_or_cp: str, ts: int
    ) -> Tuple[float, Optional[float], Optional[str]]:
        current_app.logger.debug("coingecko rate lookup %s %s", coingecko_id_or_cp, ts)
        found = 0
        source = "unknown"

        if (
            coingecko_id_or_cp in self.shortcut_rates
            and ts in self.shortcut_rates[coingecko_id_or_cp]
        ):
            rv = self.shortcut_rates[coingecko_id_or_cp][ts]
            current_app.logger.debug("shortcut hit %s %s %s", coingecko_id_or_cp, ts, rv)
            return rv

        good = float(1)
        ts = int(ts)
        # assert contract in self.contracts_map
        if coingecko_id_or_cp not in self.rates:
            current_app.logger.debug(
                "Bad rate in lookup %s %s contract is not in the rates", coingecko_id_or_cp, ts
            )

            if coingecko_id_or_cp in self.inferred_rates:
                cp_pair = coingecko_id_or_cp
                current_app.logger.debug("Contract present in inferred rates")
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

                current_app.logger.debug(
                    "coingecko add shortcut 1 %s %s %s %s %s", cp_pair, ts, good, rate, source
                )
                self.shortcut_rates[cp_pair][ts] = (good, rate, source)
                return good, rate, source
            return 0, None, None

        coingecko_id = coingecko_id_or_cp
        rates_table = self.rates[coingecko_id]

        if ts in rates_table:
            current_app.logger.debug("Exact rate for in lookup %s %s", coingecko_id, ts)
            rate = rates_table[ts]
            good = 2
            source = "exact"
        else:
            try:
                times = rates_table.keys()
                first = times[0]
                last = times[-1]
            except IndexError:
                current_app.logger.debug("failed rate lookup minmax %s %s", coingecko_id, ts)
                self.shortcut_rates[coingecko_id][ts] = (0, None, "missing")
                return 0, None, None

            if ts < first:
                found = 1
                rate = rates_table[first]
                if ts < first - 3600:
                    current_app.logger.debug(
                        "Bad rate for in lookup %s %s is smaller than first timestamp %s",
                        coingecko_id,
                        ts,
                        first,
                    )
                    good = 0.3
                    source = "before first " + str(first)
                else:
                    source = "normal"

            if ts > last:
                found = 1
                rate = rates_table[last]
                if ts > last + 3600:
                    current_app.logger.debug(
                        "Bad rate for in lookup %s %s is larger than last timestamp %s",
                        coingecko_id,
                        ts,
                        last,
                    )
                    good = 0.3
                    source = "after last " + str(last)
                else:
                    source = "normal"

            if not found:
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
                except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
                    current_app.logger.error(
                        "EXCEPTION %s in lookup_rate %s %s first=%s last=%s ts_bottom=%s ts_top=%s",
                        e,
                        coingecko_id,
                        ts,
                        first,
                        last,
                        ts_bottom,
                        ts_top,
                    )
                    return 0, None, None

        self.shortcut_rates[coingecko_id][ts] = (good, rate, source)
        current_app.logger.debug(
            "coingecko add shortcut 2 %s %s %s %s %s",
            coingecko_id,
            ts,
            good,
            rate,
            source,
        )
        return good, rate, source


class CoinGeckoApi:
    def __init__(self, rate_limit=2, timeout=10, retries=3, backoff_factor=1) -> None:
        self.api_lock = threading.Lock()
        self.session = requests.Session()
        self.last_request_time = float(0)

        if current_app.config["COINGECKO_PRO"]:
            self.session.headers.update(
                {"x-cg-pro-api-key": current_app.config["COINGECKO_API_KEY"]}
            )
            self.api_root = "https://pro-api.coingecko.com/api/v3"
        else:
            self.session.headers.update(
                {"x-cg-demo-api-key": current_app.config["COINGECKO_API_KEY"]}
            )
            self.api_root = "https://api.coingecko.com/api/v3"

        self.rate_limit = rate_limit
        self.timeout = timeout
        self.retries = retries
        self.backoff_factor = backoff_factor
        self.retry_after = int(180)

    def _request_with_retries(self, url: str, params: Dict[str, str]) -> Any:
        with self.api_lock:
            for attempt in range(1 + self.retries):
                self._rate_limit()
                try:
                    request = requests.Request(
                        HTTPMethod.GET, url, params=params, headers=self.session.headers
                    )
                    requestp = request.prepare()

                    current_app.logger.info(
                        f"Request "
                        f"{f'(retries={attempt} of {self.retries}): ' if attempt > 0 else ''}"
                        f"url={requestp.url} timeout={self.timeout}"
                    )
                    response = self.session.send(requestp, timeout=self.timeout)
                    if response.status_code == HTTPStatus.OK:
                        json = response.json()
                        return json

                    current_app.logger.error(
                        f"Bad Response "
                        f"{f'(retries={attempt} of {self.retries}): ' if attempt > 0 else ''}"
                        f"{requestp.url} status_code={response.status_code} "
                        f"content={response.content.decode()}"
                    )
                    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
                        if "retry-after" in response.headers:
                            self.retry_after = int(response.headers["retry-after"])

                        if not self._retry(attempt, self.retry_after):
                            raise CoinGeckoApiFailureBadResponse

                    if not self._retry(attempt):
                        raise CoinGeckoApiFailureBadResponse

                except requests.exceptions.JSONDecodeError as e:
                    current_app.logger.error(
                        f"Bad Response "
                        f"{f'(retries={attempt} of {self.retries}): ' if attempt > 0 else ''}"
                        f"{requestp.url} status_code={response.status_code} {e}"
                    )
                    if not self._retry(attempt):
                        raise CoinGeckoApiFailureBadResponse from e
                except (
                    requests.exceptions.ConnectionError,
                    requests.RequestException,
                    requests.exceptions.Timeout,
                ) as e:
                    current_app.logger.error(
                        f"No Response "
                        f"{f'(retries={attempt} of {self.retries}): ' if attempt > 0 else ''}"
                        f"{requestp.url} {e}"
                    )
                    if not self._retry(attempt):
                        raise CoinGeckoApiFailureNoResponse from e

            raise CoinGeckoApiFailureNoResponse

    def _rate_limit(self) -> None:
        elapsed_time = time.time() - self.last_request_time
        wait_time = (1 / self.rate_limit) - elapsed_time + 0.05

        if wait_time > 0:
            current_app.logger.debug(f"Rate-limit, wait: {wait_time:.2f} seconds")
            time.sleep(wait_time)

        self.last_request_time = time.time()

    def _retry(self, attempt: int, retry_after: Optional[int] = None) -> bool:
        if attempt < self.retries:
            if retry_after:
                wait_time = retry_after
            else:
                wait_time = self.backoff_factor * (2**attempt)

            current_app.logger.debug(f"Back-off, wait: {wait_time:.2f} seconds")
            time.sleep(wait_time)
            return True
        return False

    def coins_list(self, status: CoinGeckoCoinStatus) -> List[Any]:
        params = {"include_platform": "true"}

        if status is CoinGeckoCoinStatus.ACTIVE:
            params["status"] = "active"
        elif status is CoinGeckoCoinStatus.INACTIVE:
            params["status"] = "inactive"
        else:
            raise ValueError("Invalid CoinGeckoCoinStatus")

        url = f"{self.api_root}/coins/list"
        json = self._request_with_retries(url, params)
        for coin in json:
            coin["status"] = status.value
        return json

    def coins_markets(self, category: Optional[str] = None) -> List[Any]:
        params = {"vs_currency": "usd", "per_page": str(250), "order": "market_cap_dsc"}

        if category:
            params["category"] = category

        url = f"{self.api_root}/coins/markets"

        all_json = []
        page = 1
        while True:
            params["page"] = str(page)
            json = self._request_with_retries(url, params)
            if json:
                all_json += json
                page += 1
            else:
                break

        return all_json

    def coins_market_chart(self, coingecko_id: str, start: int, end: int) -> Dict[str, Any]:
        params = {"vs_currency": "usd", "from": str(start), "to": str(end)}
        url = f"{self.api_root}/coins/{coingecko_id}/market_chart/range"
        json = self._request_with_retries(url, params)
        return json
