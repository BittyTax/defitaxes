import os
import sys

import requests
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.chain import Chain  # noqa: E402  # pylint: disable=wrong-import-position,import-error


def fetch_covalenthq_chains() -> None:
    """Fetch list of all chains from CovalentHQ API."""

    # Load environment variables
    load_dotenv()

    api_key = os.getenv("DEFITAXES_COVALENTHQ_API_KEY")

    if not api_key:
        print("Error: DEFITAXES_COVALENTHQ_API_KEY not found in .env file")
        return None

    url = "https://api.covalenthq.com/v1/chains/"

    try:
        # Using basic auth with API key as username and empty password
        response = requests.get(url, auth=(api_key, ""), timeout=10)
        response.raise_for_status()

        data = response.json()

        # CovalentHQ API returns data in a nested structure
        chains = data.get("data", {}).get("items", [])

        return chains

    except requests.exceptions.RequestException as e:
        print(f"Error fetching data from CovalentHQ API: {e}")
        return None


def display_covalenthq_chains() -> None:
    """Display CovalentHQ chains in a formatted way."""

    chains = fetch_covalenthq_chains()

    if not chains:
        print("Failed to fetch chains from CovalentHQ")
        return

    # Filter out testnets using API's is_testnet field
    mainnet_chains = [chain for chain in chains if not chain.get("is_testnet", False)]

    # Sort chains by chain_id
    sorted_chains = sorted(
        mainnet_chains, key=lambda x: int(x.get("chain_id", 0)) if x.get("chain_id") else 0
    )

    print("=" * 140)
    print("COVALENTHQ SUPPORTED CHAINS (Mainnets Only)")
    print("=" * 140)
    print(f"\nTotal Chains: {len(sorted_chains)} (excluding testnets)\n")

    print(f"{'Chain ID':<12} {'Name':<30} {'Label':<20} {'Logo URL':<60}")
    print("-" * 140)

    for chain in sorted_chains:
        chain_id = chain.get("chain_id", "N/A")
        name = chain.get("name", "N/A")
        label = chain.get("label", "N/A")
        logo_url = chain.get("logo_url", "N/A")

        print(f"{str(chain_id):<12} {name:<30} {label:<20} {logo_url:<60}")


def validate_covalenthq_mappings() -> None:
    """Validate local chains against CovalentHQ API using both evm_chain_id and covalent_mapping."""

    covalent_chains = fetch_covalenthq_chains()

    if not covalent_chains:
        print("Failed to fetch chains from CovalentHQ")
        return

    # Filter out testnets using API's is_testnet field
    mainnet_chains = [chain for chain in covalent_chains if not chain.get("is_testnet", False)]

    # Create mapping of chain_id to covalenthq chain data
    covalent_by_chain_id = {}
    covalent_by_name = {}

    for chain in mainnet_chains:
        chain_id = chain.get("chain_id")
        name = chain.get("name")

        if chain_id is not None:
            try:
                # Convert to int to match local evm_chain_id format
                chain_id_int = int(chain_id) if isinstance(chain_id, str) else chain_id
                covalent_by_chain_id[chain_id_int] = chain
            except (ValueError, TypeError):
                # Skip if chain_id can't be converted to int
                pass

        if name:
            covalent_by_name[name.lower()] = chain

    # Get local chains
    local_chains = Chain.list(alphabetical=True, include_discontinued=False)

    print("\n" + "=" * 140)
    print("COVALENTHQ MAPPING VALIDATION")
    print("=" * 140)

    valid_evm_count = 0
    valid_mapping_count = 0
    invalid_mapping_count = 0
    no_mapping_count = 0

    # First check chains with covalent_mapping
    print("\n✓ VALID COVALENT_MAPPING (mapping matches CovalentHQ chain name AND EVM ID):")
    print("-" * 140)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        covalent_mapping = config.get("covalent_mapping")
        evm_chain_id = config.get("evm_chain_id")

        if covalent_mapping is None:
            continue

        # Check if mapping matches a CovalentHQ chain name
        if covalent_mapping.lower() in covalent_by_name:
            covalent_chain = covalent_by_name[covalent_mapping.lower()]
            covalent_chain_id = covalent_chain.get("chain_id")
            covalent_label = covalent_chain.get("label", "N/A")

            # Only mark as valid if EVM ID also matches
            if evm_chain_id and covalent_chain_id and int(covalent_chain_id) == evm_chain_id:
                valid_mapping_count += 1
                print(
                    f"  {chain_name:<20} → Mapping: {covalent_mapping:<25} | "
                    f"Chain ID: {covalent_chain_id:<10} | "
                    f"Label: {covalent_label:<20}"
                )

    print("\n✗ INVALID COVALENT_MAPPING:")
    print("-" * 140)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        covalent_mapping = config.get("covalent_mapping")
        evm_chain_id = config.get("evm_chain_id")

        if covalent_mapping is None:
            continue

        # Case 1: Mapping not found in CovalentHQ
        if covalent_mapping.lower() not in covalent_by_name:
            invalid_mapping_count += 1
            evm_info = f"EVM Chain ID: {evm_chain_id}" if evm_chain_id else "No EVM Chain ID"
            print(
                f"  {chain_name:<20} → Mapping: {covalent_mapping:<25} | "
                f"{evm_info:<20} | Error: Mapping not found on CovalentHQ"
            )
        # Case 2: Mapping found but EVM ID mismatch
        else:
            covalent_chain = covalent_by_name[covalent_mapping.lower()]
            covalent_chain_id = covalent_chain.get("chain_id")
            covalent_label = covalent_chain.get("label", "N/A")

            # Check for EVM ID mismatch
            if evm_chain_id and covalent_chain_id and int(covalent_chain_id) != evm_chain_id:
                invalid_mapping_count += 1
                print(
                    f"  {chain_name:<20} → Mapping: {covalent_mapping:<25} | "
                    f"Chain ID: {covalent_chain_id:<10} | "
                    f"Label: {covalent_label:<20} | "
                    f"Error: EVM ID mismatch (local: {evm_chain_id}, API: {covalent_chain_id})"
                )
            # Case 3: Mapping found but no EVM ID to verify
            elif not evm_chain_id:
                invalid_mapping_count += 1
                print(
                    f"  {chain_name:<20} → Mapping: {covalent_mapping:<25} | "
                    f"Chain ID: {covalent_chain_id:<10} | "
                    f"Label: {covalent_label:<20} | "
                    f"Error: No EVM Chain ID configured locally to verify"
                )

    print("\n✓ VALID EVM CHAIN ID MAPPINGS (chains available on CovalentHQ by EVM ID):")
    print("-" * 140)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        evm_chain_id = config.get("evm_chain_id")
        covalent_mapping = config.get("covalent_mapping")

        # Check if evm_chain_id exists in covalenthq chains
        if evm_chain_id in covalent_by_chain_id:
            covalent_chain = covalent_by_chain_id[evm_chain_id]
            covalent_name = covalent_chain.get("name", "N/A")
            covalent_label = covalent_chain.get("label", "N/A")

            # Check if there's a covalent_mapping and if it matches
            if covalent_mapping:
                if covalent_mapping.lower() == covalent_name.lower():
                    mapping_status = "✓ Mapping matches"
                else:
                    mapping_status = (
                        f"⚠ Mapping mismatch (local: {covalent_mapping}, API: {covalent_name})"
                    )
            else:
                mapping_status = "No covalent_mapping configured"

            valid_evm_count += 1
            print(
                f"  {chain_name:<20} → Chain ID: {evm_chain_id:<10} | "
                f"CovalentHQ: {covalent_name:<30} | "
                f"Label: {covalent_label:<20} | {mapping_status}"
            )

    print("\nℹ CHAINS WITHOUT COVALENT MAPPING:")
    print("-" * 140)

    for chain_name in local_chains:
        config = Chain.CONFIG[chain_name]
        covalent_mapping = config.get("covalent_mapping")
        evm_chain_id = config.get("evm_chain_id")

        if covalent_mapping is None:
            no_mapping_count += 1
            available = "Yes" if evm_chain_id and evm_chain_id in covalent_by_chain_id else "No"
            covalent_name = (
                covalent_by_chain_id[evm_chain_id].get("name")
                if (evm_chain_id and evm_chain_id in covalent_by_chain_id)
                else "N/A"
            )
            print(
                f"  {chain_name:<20} | EVM Chain ID: {str(evm_chain_id):<10} | "
                f"Available on CovalentHQ: {available:<5} | CovalentHQ Name: {covalent_name}"
            )

    print("\n" + "=" * 140)
    print("SUMMARY")
    print("=" * 140)
    print(f"  Valid Mappings:               {valid_mapping_count}")
    print(f"  Invalid Mappings:             {invalid_mapping_count}")
    print(f"  Valid by EVM Chain ID:        {valid_evm_count}")
    print(f"  No Mapping Configured:        {no_mapping_count}")


if __name__ == "__main__":
    display_covalenthq_chains()
    validate_covalenthq_mappings()
