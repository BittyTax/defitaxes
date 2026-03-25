import os
import sys
from collections import defaultdict

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.chain import Chain  # noqa: E402  # pylint: disable=wrong-import-position,import-error


def list_chain_apis():
    """Print a list of all chains and their APIs."""
    chains = Chain.list(alphabetical=True)

    print(f"{'Chain':<20} {'API Type':<25} {'Debank':<10} {'Covalent':<15} {'Status':<15}")
    print("-" * 85)

    for chain_name in chains:
        config = Chain.CONFIG[chain_name]
        api_type = config["api_type"].value

        # Check Debank availability
        debank = "Yes" if config.get("debank_mapping") is not None else "No"

        # Check Covalent availability
        covalent = "Yes" if "covalent_mapping" in config else "No"

        # Check if discontinued (support == 0)
        support = config.get("support", 0)
        status = "DISCONTINUED" if support == 0 else "Active"

        print(f"{chain_name:<20} {api_type:<25} {debank:<10} {covalent:<15} {status:<15}")


def list_chain_apis_by_type():
    """Print chains grouped by API type."""

    chains = Chain.list(alphabetical=True, include_discontinued=False)
    api_groups = defaultdict(list)

    for chain_name in chains:
        config = Chain.CONFIG[chain_name]
        api_type = config["api_type"].value
        api_groups[api_type].append(chain_name)

    for api_type, chain_list in sorted(api_groups.items()):
        print(f"\n{api_type}:")
        print("-" * 80)
        for chain in chain_list:
            config = Chain.CONFIG[chain]
            debank = "Yes" if config.get("debank_mapping") is not None else "No"
            covalent = "Yes" if "covalent_mapping" in config else "No"
            print(f"  {chain:<20} (Debank: {debank}  Covalent: {covalent})")


def list_debank_chains():
    """Print chains that support Debank."""
    chains = Chain.list(alphabetical=True, include_discontinued=False)

    print("\n" + "=" * 80)
    print("ACTIVE CHAINS WITH DEBANK SUPPORT")
    print("=" * 80)

    debank_chains = []
    no_debank_chains = []

    for chain_name in chains:
        config = Chain.CONFIG[chain_name]

        if config.get("debank_mapping") is not None:
            debank_chains.append((chain_name, config["debank_mapping"]))
        else:
            no_debank_chains.append(chain_name)

    print(f"\nSupported ({len(debank_chains)} chains):")
    print("-" * 80)
    for chain, mapping in debank_chains:
        print(f"  {chain:<20} → {mapping}")

    print(f"\nNot Supported ({len(no_debank_chains)} chains):")
    print("-" * 80)
    for chain in no_debank_chains:
        print(f"  {chain}")


def list_covalent_chains():
    """Print chains that support Covalent."""
    chains = Chain.list(alphabetical=True, include_discontinued=False)

    print("\n" + "=" * 80)
    print("ACTIVE CHAINS WITH COVALENT SUPPORT")
    print("=" * 80)

    covalent_chains = []
    no_covalent_chains = []

    for chain_name in chains:
        config = Chain.CONFIG[chain_name]

        if "covalent_mapping" in config:
            covalent_chains.append((chain_name, config["covalent_mapping"]))
        else:
            no_covalent_chains.append(chain_name)

    print(f"\nSupported ({len(covalent_chains)} chains):")
    print("-" * 80)
    for chain, mapping in covalent_chains:
        print(f"  {chain:<20} → {mapping}")

    print(f"\nNot Supported ({len(no_covalent_chains)} chains):")
    print("-" * 80)
    for chain in no_covalent_chains:
        print(f"  {chain}")


def summary_stats():
    """Print summary statistics."""
    chains = Chain.list(include_discontinued=False)

    api_counts = {}
    debank_count = 0
    covalent_count = 0
    discontinued_count = 0
    active_count = 0

    for chain_name in chains:
        config = Chain.CONFIG[chain_name]

        api_type = config["api_type"].value
        api_counts[api_type] = api_counts.get(api_type, 0) + 1

        if config.get("debank_mapping") is not None:
            debank_count += 1

        if "covalent_mapping" in config:
            covalent_count += 1

        support = config.get("support", 0)
        if support == 0:
            discontinued_count += 1
        else:
            active_count += 1

    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"\nTotal Chains: {len(chains)}")
    print(f"Active Chains: {active_count}")
    print(f"Discontinued Chains: {discontinued_count}")
    print("\nAPI Types:")
    for api_type, count in sorted(api_counts.items()):
        print(f"  {api_type:<30} {count:>3} chains")
    print("\nIntegrations:")
    print(f"  Debank:   {debank_count:>3} chains")
    print(f"  Covalent: {covalent_count:>3} chains")


if __name__ == "__main__":
    print("=" * 85)
    print("CHAINS AND THEIR APIS")
    print("=" * 85)
    list_chain_apis()

    print("\n\n" + "=" * 80)
    print("ACTIVE CHAINS GROUPED BY API TYPE")
    print("=" * 80)
    list_chain_apis_by_type()

    list_debank_chains()
    list_covalent_chains()
    summary_stats()
