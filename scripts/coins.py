import json
import os
import time
from collections import defaultdict
from typing import Dict, List

import requests
from dotenv import load_dotenv

load_dotenv()


class CoinGeckoAnalyzer:
    """Analyze CoinGecko coins list with API key support."""

    PRO_KEY = "x-cg-pro-api-key"

    def __init__(self):
        """Initialize with API keys from environment variables."""
        self.headers = {"User-Agent": "BittyTax Analysis Script"}

        api_key = os.getenv("DEFITAXES_COINGECKO_API_KEY")
        self.headers[self.PRO_KEY] = api_key
        self.api_root = "https://pro-api.coingecko.com/api/v3"
        self.api_type = "PRO"

    def fetch_coins(self, status: str = "active") -> List[Dict]:
        """Fetch coins list by status (active or inactive)."""
        url = f"{self.api_root}/coins/list?include_platform=true&status={status}"

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching {status} coins: {e}")
            return []

    def fetch_market_data(self) -> Dict[str, float]:
        """Fetch market cap data for all coins."""
        market_caps = {}
        page = 1
        per_page = 250

        print("Fetching market cap data...")

        while True:
            url = (
                f"{self.api_root}/coins/markets"
                f"?vs_currency=usd&order=market_cap_desc"
                f"&per_page={per_page}&page={page}"
                f"&sparkline=false"
            )

            try:
                response = requests.get(url, headers=self.headers, timeout=30)
                response.raise_for_status()
                data = response.json()

                if not data:
                    break

                for coin in data:
                    coin_id = coin.get("id")
                    market_cap = coin.get("market_cap")
                    if coin_id and market_cap is not None:
                        market_caps[coin_id] = market_cap

                print(f"  Fetched page {page} ({len(data)} coins, total: {len(market_caps)})")
                page += 1

                if page > 1:
                    time.sleep(0.5)

            except requests.RequestException as e:
                print(f"Error fetching market data page {page}: {e}")
                break

        print(f"Total market cap data retrieved for {len(market_caps)} coins")
        return market_caps

    def _format_market_cap(self, market_cap: float) -> str:
        """Format market cap in human readable format (k, M, B)."""
        if market_cap == 0:
            return "No data"
        if market_cap >= 1_000_000_000:
            return f"${market_cap / 1_000_000_000:.2f}B"
        if market_cap >= 1_000_000:
            return f"${market_cap / 1_000_000:.2f}M"
        if market_cap >= 1_000:
            return f"${market_cap / 1_000:.2f}K"
        return f"${market_cap:.2f}"

    def analyze_coins_by_symbol(
        self, active_coins: List[Dict], inactive_coins: List[Dict], market_caps: Dict[str, float]
    ) -> Dict[str, List[Dict]]:
        """Analyze coins by symbol and combine active/inactive data."""
        symbol_map = defaultdict(list)

        for coin in active_coins:
            symbol = coin.get("symbol", "").upper()
            coin_id = coin.get("id")
            name = coin.get("name", "")
            market_cap = market_caps.get(coin_id, 0)
            symbol_map[symbol].append(
                {"id": coin_id, "name": name, "market_cap": market_cap, "status": "active"}
            )

        for coin in inactive_coins:
            symbol = coin.get("symbol", "").upper()
            coin_id = coin.get("id")
            name = coin.get("name", "")
            market_cap = market_caps.get(coin_id, 0)
            symbol_map[symbol].append(
                {"id": coin_id, "name": name, "market_cap": market_cap, "status": "inactive"}
            )

        # Sort coins for each symbol by market cap in descending order
        for symbol in symbol_map:
            symbol_map[symbol].sort(key=lambda x: x["market_cap"], reverse=True)

        return symbol_map

    def print_analysis(
        self, symbol_map: Dict[str, List[Dict]], active_count: int, inactive_count: int
    ) -> None:
        """Print analysis results."""
        single = {s: coins for s, coins in symbol_map.items() if len(coins) == 1}
        multi = {s: coins for s, coins in symbol_map.items() if len(coins) > 1}

        print(f"Total unique symbols: {len(symbol_map)}")
        print(f"Symbols with single coin ID: {len(single)}")
        print(f"Symbols with multiple coin IDs: {len(multi)}")
        print(f"Active coins: {active_count}")
        print(f"Inactive coins: {inactive_count}")
        print()

        print("COIN ID ANALYSIS BY SYMBOL:")
        print("-" * 120)
        print()

        for symbol in sorted(symbol_map.keys()):
            coins = symbol_map[symbol]
            active_cnt = sum(1 for c in coins if c["status"] == "active")
            inactive_cnt = sum(1 for c in coins if c["status"] == "inactive")

            print(
                f'"{symbol}" ({len(coins)} coins - {active_cnt} active, {inactive_cnt} inactive):'
            )
            for i, coin in enumerate(coins, 1):
                status_label = "[ACTIVE]  " if coin["status"] == "active" else "[INACTIVE]"
                market_cap_str = self._format_market_cap(coin["market_cap"])
                print(
                    f"  {i:>3}. {status_label}   {market_cap_str:>12}   "
                    f"{coin['id']:<45} - {coin['name']}"
                )
            print()

    def save_to_json(self, symbol_map: Dict[str, List[Dict]]) -> None:
        """Save analysis results to a JSON file."""
        with open("coin_analysis.json", "w", encoding="utf-8") as f:
            json.dump(symbol_map, f, indent=4)
        print("Analysis saved to coin_analysis.json")


def main():
    print("CoinGecko Coins List Analyzer")
    print("=" * 120)
    print()

    analyzer = CoinGeckoAnalyzer()

    print(f"Using {analyzer.api_type} API")
    print()

    print("Fetching active coins...")
    active_coins = analyzer.fetch_coins("active")
    print(f"Retrieved {len(active_coins)} active coins")

    inactive_coins = []
    if analyzer.api_type == "PRO":
        print("Fetching inactive coins...")
        inactive_coins = analyzer.fetch_coins("inactive")
        print(f"Retrieved {len(inactive_coins)} inactive coins")
    else:
        print("Inactive coins require Pro API - skipping")

    print()

    market_caps = analyzer.fetch_market_data()
    print()

    if not active_coins and not inactive_coins:
        print("No data retrieved. Exiting.")
        return

    symbol_map = analyzer.analyze_coins_by_symbol(active_coins, inactive_coins, market_caps)
    analyzer.print_analysis(symbol_map, len(active_coins), len(inactive_coins))
    analyzer.save_to_json(symbol_map)


if __name__ == "__main__":
    main()
