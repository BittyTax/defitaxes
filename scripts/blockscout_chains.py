# Get list of chains supported by the Blockscout V2 API

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

    scanner = scanner.replace("https://", "").replace("http://", "")
    scanner = scanner.rstrip("/")

    return scanner


def fetch_blockscout_chains():
    """Fetch list of all chains from Blockscout V2 API."""

    api_key = os.environ.get("DEFITAXES_BLOCKSCOUT_API_KEY", "")
    url = "https://api.blockscout.com/multichain/api/v1/clusters/multichain/chains"

    if api_key:
        url = f"{url}?apikey={api_key}"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        return data.get("items", [])

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from Blockscout API: {e}")
        return None


def display_blockscout_chains():
    """Display Blockscout chains in a formatted way."""

    chains = fetch_blockscout_chains()

    if not chains:
        print("Failed to fetch chains from Blockscout")
        return

    sorted_chains = sorted(chains, key=lambda x: x.get("name", ""))

    print("=" * 100)
    print("BLOCKSCOUT V2 SUPPORTED CHAINS")
    print("=" * 100)
    print(f"\nTotal Chains: {len(sorted_chains)}\n")

    print(f"{'Chain Name':<40} {'Explorer URL':<45} {'Chain ID':<15}")
    print("-" * 100)

    for chain in sorted_chains:
        chainname = chain.get("name", "N/A")
        explorer_url = chain.get("explorer_url", "N/A")
        chainid = chain.get("id", "N/A")

        print(f"{chainname:<40} {str(explorer_url):<45} {str(chainid):<15}")


def validate_blockscout_v1_chains():
    """Validate local chains using BLOCKSCOUT_V1 API type.

    For V1 chains:
    - api_url should be https://<scanner>/api
    - scanner should match the host portion of api_url
    """

    local_chains = Chain.list(alphabetical=True, include_discontinued=True)

    print("\n" + "=" * 120)
    print("BLOCKSCOUT V1 CHAIN VALIDATION")
    print("=" * 120)
    print("Rules: api_url should be 'https://<scanner>/api'")
    print("-" * 120)

    valid_count = 0
    invalid_count = 0
    missing_api_url_count = 0

    valid_chains = []
    invalid_chains = []
    missing_api_url_chains = []

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        api_type = config.get("api_type")

        if api_type != ChainApiType.BLOCKSCOUT_V1:
            continue

        scanner = config.get("scanner", "")
        api_url = config.get("api_url", "")

        if not api_url:
            missing_api_url_count += 1
            missing_api_url_chains.append((chain_name, scanner, api_url))
            continue

        # Expected api_url based on scanner
        expected_api_url = f"https://{scanner}/api"
        normalized_api_url = api_url.rstrip("/")

        if normalized_api_url == expected_api_url:
            valid_count += 1
            valid_chains.append((chain_name, scanner, api_url))
        else:
            invalid_count += 1
            invalid_chains.append((chain_name, scanner, api_url, expected_api_url))

    print("\n✓ VALID V1 CHAINS (api_url matches https://<scanner>/api):")
    print("-" * 120)
    for chain_name, scanner, api_url in valid_chains:
        print(f"  {chain_name:<20} | Scanner: {scanner:<40} | api_url: {api_url}")

    print("\n⚠ INVALID V1 CHAINS (api_url does not match https://<scanner>/api):")
    print("-" * 120)
    for chain_name, scanner, api_url, expected_api_url in invalid_chains:
        print(
            f"  {chain_name:<20} | Scanner: {scanner:<40} | "
            f"api_url: {api_url:<50} | Expected: {expected_api_url}"
        )

    print("\n✗ V1 CHAINS MISSING api_url:")
    print("-" * 120)
    for chain_name, scanner, _ in missing_api_url_chains:
        expected_api_url = f"https://{scanner}/api"
        print(f"  {chain_name:<20} | Scanner: {scanner:<40} | Expected api_url: {expected_api_url}")

    print("\n" + "=" * 120)
    print("BLOCKSCOUT V1 SUMMARY")
    print("=" * 120)
    print(f"  Valid (api_url matches expected):   {valid_count}")
    print(f"  Invalid (api_url mismatch):          {invalid_count}")
    print(f"  Missing api_url:                     {missing_api_url_count}")
    print(
        f"  Total V1 chains:                     {valid_count + invalid_count + missing_api_url_count}"
    )


def validate_blockscout_v2_chains():
    """Validate local chains using BLOCKSCOUT_V2 API type against Blockscout multichain API."""

    blockscout_chains = fetch_blockscout_chains()

    if not blockscout_chains:
        print("Failed to fetch chains from Blockscout")
        return

    # Create mapping of chain_id to blockscout chain data
    blockscout_by_chain_id = {}
    for chain in blockscout_chains:
        chain_id = chain.get("id")
        if chain_id is not None:
            try:
                chain_id_int = int(chain_id)
                blockscout_by_chain_id[chain_id_int] = chain
            except (ValueError, TypeError):
                pass

    local_chains = Chain.list(alphabetical=True, include_discontinued=True)

    print("\n" + "=" * 120)
    print("BLOCKSCOUT V2 CHAIN VALIDATION")
    print("=" * 120)
    print("Rules: scanner should match explorer_url from Blockscout multichain API")
    print("-" * 120)

    valid_count = 0
    scanner_mismatch_count = 0
    not_in_api_count = 0
    missing_chain_id_count = 0

    valid_chains = []
    scanner_mismatch_chains = []
    not_in_api_chains = []
    missing_chain_id_chains = []

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        api_type = config.get("api_type")

        if api_type != ChainApiType.BLOCKSCOUT_V2:
            continue

        scanner = config.get("scanner", "")
        evm_chain_id = config.get("evm_chain_id")

        if not evm_chain_id:
            missing_chain_id_count += 1
            missing_chain_id_chains.append((chain_name, scanner))
            continue

        if evm_chain_id not in blockscout_by_chain_id:
            not_in_api_count += 1
            not_in_api_chains.append((chain_name, scanner, evm_chain_id))
            continue

        blockscout_chain = blockscout_by_chain_id[evm_chain_id]
        blockscout_scanner = normalize_scanner(blockscout_chain.get("explorer_url", "N/A"))
        normalized_local = normalize_scanner(scanner)

        if normalized_local == blockscout_scanner:
            valid_count += 1
            valid_chains.append((chain_name, scanner, evm_chain_id))
        else:
            scanner_mismatch_count += 1
            scanner_mismatch_chains.append((chain_name, scanner, evm_chain_id, blockscout_scanner))

    # Also check chains that COULD be V2 (found in API but not using V2)
    should_be_v2_chains = []
    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        api_type = config.get("api_type")
        evm_chain_id = config.get("evm_chain_id")

        if api_type != ChainApiType.BLOCKSCOUT_V2 and evm_chain_id in blockscout_by_chain_id:
            blockscout_chain = blockscout_by_chain_id[evm_chain_id]
            blockscout_scanner = normalize_scanner(blockscout_chain.get("explorer_url", "N/A"))
            current_api = api_type.value if api_type else "N/A"
            should_be_v2_chains.append((chain_name, evm_chain_id, current_api, blockscout_scanner))

    print("\n✓ VALID V2 CHAINS (scanner matches Blockscout API):")
    print("-" * 120)
    for chain_name, scanner, chain_id in valid_chains:
        print(f"  {chain_name:<20} | Chain ID: {chain_id:<10} | Scanner: {scanner}")

    print("\n⚠ V2 CHAINS WITH SCANNER MISMATCH:")
    print("-" * 120)
    for chain_name, scanner, chain_id, expected_scanner in scanner_mismatch_chains:
        print(
            f"  {chain_name:<20} | Chain ID: {chain_id:<10} | "
            f"Local: {scanner:<40} | Expected: {expected_scanner}"
        )

    print("\n✗ V2 CHAINS NOT FOUND IN BLOCKSCOUT API:")
    print("-" * 120)
    for chain_name, scanner, chain_id in not_in_api_chains:
        print(f"  {chain_name:<20} | Chain ID: {chain_id:<10} | Scanner: {scanner}")

    print("\n✗ V2 CHAINS MISSING evm_chain_id:")
    print("-" * 120)
    for chain_name, scanner in missing_chain_id_chains:
        print(f"  {chain_name:<20} | Scanner: {scanner}")

    print("\nℹ CHAINS AVAILABLE ON BLOCKSCOUT V2 API BUT NOT USING BLOCKSCOUT_V2:")
    print("-" * 120)
    for chain_name, chain_id, current_api, blockscout_scanner in should_be_v2_chains:
        print(
            f"  {chain_name:<20} | Chain ID: {chain_id:<10} | "
            f"Current API: {current_api:<30} | Blockscout Scanner: {blockscout_scanner}"
        )

    print("\n" + "=" * 120)
    print("BLOCKSCOUT V2 SUMMARY")
    print("=" * 120)
    print(f"  Valid (scanner matches API):                  {valid_count}")
    print(f"  Scanner mismatch:                             {scanner_mismatch_count}")
    print(f"  Not found in Blockscout API:                  {not_in_api_count}")
    print(f"  Missing evm_chain_id:                         {missing_chain_id_count}")
    print(f"  Could be upgraded to BLOCKSCOUT_V2:           {len(should_be_v2_chains)}")
    print(f"  Total Blockscout supported chains (API):      {len(blockscout_chains)}")


if __name__ == "__main__":
    display_blockscout_chains()
    validate_blockscout_v1_chains()
    validate_blockscout_v2_chains()
