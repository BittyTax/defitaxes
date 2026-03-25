# Get list of chains supported by the Etherscan V2 API

import os
import sys

import requests

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.chain import (  # noqa: E402  # pylint: disable=wrong-import-position,import-error
    Chain,
    ChainApiType,
)


def normalize_scanner(scanner):
    """Normalize scanner URL by removing protocol and trailing slash."""
    if not scanner or scanner == "N/A":
        return scanner

    # Remove https:// or http://
    scanner = scanner.replace("https://", "").replace("http://", "")
    # Remove trailing slash
    scanner = scanner.rstrip("/")

    return scanner


def fetch_etherscan_chains():
    """Fetch list of all chains from Etherscan V2 API."""

    url = "https://api.etherscan.io/v2/chainlist"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        result = data.get("result", [])

        # Filter out testnets and inactive chains
        active_chains = [
            chain
            for chain in result
            if not chain.get("chainname", "").endswith(" Testnet") and chain.get("status", 0) > 0
        ]

        return active_chains

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from Etherscan API: {e}")
        return None


def display_etherscan_chains():
    """Display Etherscan chains in a formatted way."""

    chains = fetch_etherscan_chains()

    if not chains:
        print("Failed to fetch chains from Etherscan")
        return

    # Sort chains by name
    sorted_chains = sorted(chains, key=lambda x: x.get("chainname", ""))

    print("=" * 100)
    print("ETHERSCAN V2 SUPPORTED CHAINS")
    print("=" * 100)
    print(f"\nTotal Chains: {len(sorted_chains)}\n")

    print(f"{'Chain Name':<30} {'Block Explorer':<40} {'Chain ID':<15}")
    print("-" * 100)

    for chain in sorted_chains:
        chainname = chain.get("chainname", "N/A")
        # Remove " Mainnet" suffix if present
        if chainname.endswith(" Mainnet"):
            chainname = chainname[:-8]

        blockexplorer = chain.get("blockexplorer", "N/A")
        chainid = chain.get("chainid", "N/A")

        print(f"{chainname:<30} {blockexplorer:<40} {str(chainid):<15}")


def validate_etherscan_mappings():
    """Validate local chains using ETHERSCAN_V2 API type against Etherscan API."""

    etherscan_chains = fetch_etherscan_chains()

    if not etherscan_chains:
        print("Failed to fetch chains from Etherscan")
        return

    # Create mapping of chain_id to etherscan chain data
    # Convert chain_id to int to ensure proper matching
    etherscan_by_chain_id = {}
    for chain in etherscan_chains:
        chain_id = chain.get("chainid")
        if chain_id is not None:
            # Convert to int if it's a string
            try:
                chain_id_int = int(chain_id)
                etherscan_by_chain_id[chain_id_int] = chain
            except (ValueError, TypeError):
                pass

    # Get local chains
    local_chains = Chain.list(alphabetical=True, include_discontinued=False)

    print("\n" + "=" * 120)
    print("ETHERSCAN V2 API TYPE VALIDATION")
    print("=" * 120)

    valid_count = 0
    id_match_scanner_mismatch_count = 0
    missing_etherscan_count = 0
    should_use_etherscan_count = 0
    using_etherscan_count = 0

    print("\n✓ CHAINS CORRECTLY USING ETHERSCAN_V2 (ID and Scanner Match):")
    print("-" * 120)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        api_type = config.get("api_type")
        evm_chain_id = config.get("evm_chain_id")
        scanner = config.get("scanner", "N/A")

        if api_type == ChainApiType.ETHERSCAN_V2:
            using_etherscan_count += 1

            if evm_chain_id and evm_chain_id in etherscan_by_chain_id:
                etherscan_chain = etherscan_by_chain_id[evm_chain_id]
                etherscan_scanner = etherscan_chain.get("blockexplorer", "N/A")

                # Normalize both scanners for comparison
                normalized_local = normalize_scanner(scanner)
                normalized_etherscan = normalize_scanner(etherscan_scanner)

                # Check if scanner matches
                if normalized_local == normalized_etherscan:
                    valid_count += 1
                    print(f"  {chain_name:<20} | Chain ID: {evm_chain_id:<10} | Scanner: {scanner}")

    print("\n⚠ CHAINS USING ETHERSCAN_V2 WITH ID MATCH BUT SCANNER MISMATCH:")
    print("-" * 120)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        api_type = config.get("api_type")
        evm_chain_id = config.get("evm_chain_id")
        scanner = config.get("scanner", "N/A")

        if api_type == ChainApiType.ETHERSCAN_V2:
            if evm_chain_id and evm_chain_id in etherscan_by_chain_id:
                etherscan_chain = etherscan_by_chain_id[evm_chain_id]
                etherscan_scanner = etherscan_chain.get("blockexplorer", "N/A")

                # Normalize both scanners for comparison
                normalized_local = normalize_scanner(scanner)
                normalized_etherscan = normalize_scanner(etherscan_scanner)

                # Check if scanner doesn't match
                if normalized_local != normalized_etherscan:
                    id_match_scanner_mismatch_count += 1
                    print(
                        f"  {chain_name:<20} | Chain ID: {evm_chain_id:<10} | "
                        f"Local: {scanner:<40} | "
                        f"Expected: {normalize_scanner(etherscan_scanner)}"
                    )

    print("\n✗ CHAINS USING ETHERSCAN_V2 BUT NOT FOUND IN ETHERSCAN API:")
    print("-" * 120)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        api_type = config.get("api_type")
        evm_chain_id = config.get("evm_chain_id")
        scanner = config.get("scanner", "N/A")

        if api_type == ChainApiType.ETHERSCAN_V2:
            if evm_chain_id and evm_chain_id not in etherscan_by_chain_id:
                missing_etherscan_count += 1
                print(
                    f"  {chain_name:<20} | Chain ID: {evm_chain_id:<10} | "
                    f"Scanner: {scanner} (NOT IN ETHERSCAN)"
                )

    print("\nℹ CHAINS AVAILABLE ON ETHERSCAN BUT NOT USING ETHERSCAN_V2:")
    print("-" * 120)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        api_type = config.get("api_type")
        evm_chain_id = config.get("evm_chain_id")
        scanner = config.get("scanner", "N/A")

        if api_type != ChainApiType.ETHERSCAN_V2:
            if evm_chain_id and evm_chain_id in etherscan_by_chain_id:
                should_use_etherscan_count += 1
                etherscan_chain = etherscan_by_chain_id[evm_chain_id]
                current_api = api_type.value if api_type else "N/A"
                etherscan_scanner = etherscan_chain.get("blockexplorer", "N/A")
                print(
                    f"  {chain_name:<20} | Chain ID: {evm_chain_id:<10} | "
                    f"Current API: {current_api:<25} | "
                    f"Etherscan Scanner: {normalize_scanner(etherscan_scanner)}"
                )

    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    print(f"  Chains using ETHERSCAN_V2:                    {using_etherscan_count}")
    print(f"  Valid (ID and Scanner match):                 {valid_count}")
    print(f"  ID match but Scanner mismatch:                {id_match_scanner_mismatch_count}")
    print(f"  ETHERSCAN_V2 chains not in Etherscan API:     {missing_etherscan_count}")
    print(f"  Chains that could use ETHERSCAN_V2:           {should_use_etherscan_count}")
    print(f"  Total Etherscan supported chains:             {len(etherscan_chains)}")
    print(f"  Total local chains:                           {len(local_chains)}")


if __name__ == "__main__":
    display_etherscan_chains()
    validate_etherscan_mappings()
