import os
import sys

import requests
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.chain import Chain  # noqa: E402  # pylint: disable=wrong-import-position,import-error


def fetch_debank_chains():
    """Fetch list of all chains from Debank API."""

    # Load environment variables
    load_dotenv()

    api_key = os.getenv("DEFITAXES_DEBANK_API_KEY")

    if not api_key:
        print("Error: DEFITAXES_DEBANK_API_KEY not found in .env file")
        return None

    url = "https://pro-openapi.debank.com/v1/chain/list"
    headers = {"accept": "application/json", "AccessKey": api_key}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        chains = response.json()

        return chains

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from Debank API: {e}")
        return None


def display_debank_chains():
    """Display Debank chains in a formatted way."""

    chains = fetch_debank_chains()

    if not chains:
        print("Failed to fetch chains from Debank")
        return

    # Sort chains by ID
    sorted_chains = sorted(chains, key=lambda x: x.get("id", ""))

    print("=" * 120)
    print("DEBANK SUPPORTED CHAINS")
    print("=" * 120)
    print(f"\nTotal Chains: {len(sorted_chains)}\n")

    print(
        f"{'ID':<20} {'Name':<25} {'Native Token':<15} {'Community ID':<15} {'Wrapped Token':<45}"
    )
    print("-" * 120)

    for chain in sorted_chains:
        chain_id = chain.get("id", "N/A")
        name = chain.get("name", "N/A")
        native_token = chain.get("native_token_id", "N/A")
        community_id = chain.get("community_id", "N/A")
        wrapped_token = chain.get("wrapped_token_id", "N/A")

        print(
            (
                f"{chain_id:<20} {name:<25} {native_token:<15} "
                f"{str(community_id):<15} {wrapped_token:<45}"
            )
        )


def validate_debank_mappings():
    """Validate local debank_mapping against Debank API using evm_chain_id."""

    debank_chains = fetch_debank_chains()

    if not debank_chains:
        print("Failed to fetch chains from Debank")
        return

    # Create mapping of community_id to debank chain data
    debank_by_community_id = {}
    for chain in debank_chains:
        community_id = chain.get("community_id")
        if community_id is not None:
            debank_by_community_id[community_id] = chain

    # Get local chains
    local_chains = Chain.list(alphabetical=True, include_discontinued=False)

    print("\n" + "=" * 120)
    print("DEBANK MAPPING VALIDATION")
    print("=" * 120)

    valid_count = 0
    invalid_count = 0
    no_mapping_count = 0

    print("\n✓ VALID MAPPINGS:")
    print("-" * 120)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        debank_mapping = config.get("debank_mapping")
        evm_chain_id = config.get("evm_chain_id")

        if debank_mapping is None:
            continue

        # Check if evm_chain_id exists in debank chains
        if evm_chain_id and evm_chain_id in debank_by_community_id:
            debank_chain = debank_by_community_id[evm_chain_id]
            expected_id = debank_chain.get("id")

            if debank_mapping == expected_id:
                valid_count += 1
                print(f"  {chain_name:<20} → {debank_mapping:<20} (EVM Chain ID: {evm_chain_id})")

    print("\n✗ INVALID MAPPINGS:")
    print("-" * 120)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        debank_mapping = config.get("debank_mapping")
        evm_chain_id = config.get("evm_chain_id")

        if debank_mapping is None:
            continue

        # Case 1: EVM chain ID exists in Debank but mapping doesn't match
        if evm_chain_id and evm_chain_id in debank_by_community_id:
            debank_chain = debank_by_community_id[evm_chain_id]
            expected_id = debank_chain.get("id")

            if debank_mapping != expected_id:
                invalid_count += 1
                print(
                    f"  {chain_name:<20} → Current: {debank_mapping:<20} | "
                    f"Expected: {expected_id:<20} (EVM Chain ID: {evm_chain_id})"
                )
        # Case 2: EVM chain ID does not exist in Debank
        else:
            invalid_count += 1
            print(
                f"  {chain_name:<20} → Current: {debank_mapping:<20} | "
                f"EVM Chain ID: {str(evm_chain_id):<10} | Error: Chain not found on Debank"
            )

    print("\nℹ CHAINS WITHOUT DEBANK MAPPING:")
    print("-" * 120)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        debank_mapping = config.get("debank_mapping")
        evm_chain_id = config.get("evm_chain_id")

        if debank_mapping is None:
            no_mapping_count += 1
            available = "Yes" if evm_chain_id and evm_chain_id in debank_by_community_id else "No"
            debank_id = (
                debank_by_community_id[evm_chain_id].get("id")
                if (evm_chain_id and evm_chain_id in debank_by_community_id)
                else "N/A"
            )
            print(
                f"  {chain_name:<20} | EVM Chain ID: {str(evm_chain_id):<10} | "
                f"Available on Debank: {available:<5} | Debank ID: {debank_id}"
            )

    print("\n" + "=" * 120)
    print("SUMMARY")
    print("=" * 120)
    print(f"  Valid Mappings:        {valid_count}")
    print(f"  Invalid Mappings:      {invalid_count}")
    print(f"  No Mapping Configured: {no_mapping_count}")


if __name__ == "__main__":
    display_debank_chains()
    validate_debank_mappings()
