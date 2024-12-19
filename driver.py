# -*- coding: utf-8 -*-
import os

import click
from flask import Blueprint, current_app

from app.coingecko import Coingecko
from app.signatures import Signatures
from app.sqlite import SQLite
from app.tax_calc import Calculator
from app.user import User
from app.util import log

driver = Blueprint("driver", __name__)


@driver.cli.command("process")
@click.argument("address")
@click.argument("chain_name")
@click.option(
    "--import", "do_import", is_flag=True, show_default=True, default=True, help="Do import"
)
@click.option(
    "--lookups", "do_lookups", is_flag=True, show_default=True, default=True, help="Do lookups"
)
@click.option(
    "--calc", "do_calc", is_flag=True, show_default=True, default=True, help="Do tax calculations"
)
def process(address, chain_name, do_import=True, do_lookups=True, do_calc=True):
    current_app.config["DEBUG_LEVEL"] = 2
    chain_names = [chain_name]
    S = Signatures()
    C = Coingecko(verbose=False)
    user = User(address, do_logging=False)
    user.wipe_transactions()
    user.set_address_present(address, chain_names[0], value=1, commit=True)
    user.set_address_used(address, chain_names[0], value=1, commit=True)

    # chain_names = Chain.list()
    chains = {}
    for chain_name in chain_names:
        chains[chain_name] = {
            "chain": user.chain_factory(chain_name),
            "current_tokens": {},
            "is_upload": False,
        }

    user.get_custom_rates()

    address_db = SQLite("addresses")
    for chain_name, chain in chains.items():
        chain["chain"].init_addresses(address_db)

    if do_import:
        user.start_import(chains)
        for chain_name, chain_data in chains.items():
            chain_data["import_addresses"] = [address]
            chain = chain_data["chain"]
            transactions = chain.get_transactions(user, address, 0)  # alloc 20
            chain_data["transactions"] = transactions
            chain.correct_transactions(address, transactions, 0)  # alloc 5
            current_tokens = chain.get_current_tokens(address)
            chain_data["current_tokens"][address] = current_tokens
            chain.covalent_download(chain_data)
            chain.covalent_correction(chain_data)

        user.get_thirdparty_data(chains)
        for chain_name, chain_data in chains.items():
            chain = chain_data["chain"]
            chain.balance_provider_correction(chain_data)

        for chain_name, chain_data in chains.items():
            chain = chain_data["chain"]
            print("Storing transactions", chain, len(chain_data["transactions"]))
            user.store_transactions(chain_data["chain"], chain_data["transactions"], address, C)
            user.store_current_tokens(chain_data["chain"], chain_data["current_tokens"])

    user.load_addresses()
    user.load_tx_counts()

    transactions, _ = user.load_transactions(chains)
    print("Loaded transactions", len(transactions))
    contract_dict, counterparty_by_chain, input_list = user.get_contracts(transactions)
    if do_lookups:
        print("contract_dict", contract_dict)
        print("counterparty_by_chain", counterparty_by_chain)
        for chain_name, chain_data in chains.items():
            chain = chain_data["chain"]
            filtered_counterparty_list = chain.filter_progenitors(
                list(counterparty_by_chain[chain_name])
            )
            print(chain_name, "counterparty_list", filtered_counterparty_list)
            if len(filtered_counterparty_list) > 0:
                chain_data["progenitor_db_writes"] = chain.update_progenitors(
                    filtered_counterparty_list, 0
                )  # alloc 30

        all_db_writes = []
        for chain_name, chain_data in chains.items():
            if "progenitor_db_writes" in chain_data:
                all_db_writes.extend(chain_data["progenitor_db_writes"])

        if all_db_writes:
            insert_cnt = 0
            for write in all_db_writes:
                chain_name, values = write
                entity = values[-2]
                address_to_add = values[0]
                rc = address_db.insert_kw(
                    chain_name + "_addresses", values=values, ignore=(entity == "unknown")
                )
                if rc > 0:
                    address_db.insert_kw(
                        chain_name + "_labels", values=[address_to_add, "auto"], ignore=True
                    )
                    insert_cnt += 1
            if insert_cnt > 0:
                address_db.commit()
                log("New addresses added", insert_cnt, filename="address_lookups.txt")

    S.init_from_db(input_list)
    needed_token_times = user.get_needed_token_times(transactions)

    C.init_from_db_2(chains, needed_token_times)
    if do_import:
        user.finish_import()
    user.load_current_tokens(C)
    address_db.disconnect()

    transactions_js = user.transactions_to_log(C, S, transactions, store_derived=True)  # alloc 20
    print("do_calc", do_calc)
    if do_calc:
        user.load_custom_types()
        calculator = Calculator(user, C)
        calculator.process_transactions(transactions_js, user)
        calculator.matchup()
        calculator.cache()

        log("Calculator summary", calculator.CA_short)


if __name__ == "__main__":
    # address = "0xd603a49886c9b500f96c0d798aed10068d73bf7c"
    # address = "95iZStZPdxWoKUfinEtxq8X7SfTn496D1tKDiUuyNeqC"  # solana
    # address = "9HdPeqZGJDTtoHoGz4x6vNoPBxhnQLazjmfzYAjAiZVK"
    os.system("flask driver process 0x032b7d93aeed91127baa55ad570d88fd2f15d589 Arbitrum")
