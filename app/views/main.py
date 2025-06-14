import html
import json
import os
import threading
import time
import traceback

from flask import Blueprint, current_app, render_template, request

from ..chain import Chain
from ..coingecko import Coingecko
from ..constants import USER_DIRNAME
from ..evm_api import EtherscanV1Api, EtherscanV2Api
from ..fiat_rates import Twelve
from ..redis_wrap import ProgressBar, Redis
from ..signatures import Signatures
from ..sqlite import SQLite
from ..tax_calc import Calculator
from ..user import Import, User
from ..util import log, log_error, normalize_address, sql_in

main = Blueprint("main", __name__)


@main.route("/")
def index():
    address_cookie = request.cookies.get("address")
    address = ""
    if address_cookie is not None:
        if "|" in address_cookie:
            address, _ = address_cookie.split("|")
        else:
            address = address_cookie

    blockchain_count = len(Chain.CONFIG)
    return render_template(
        "index.html",
        title="Blockchain transactions to US tax form",
        address=address,
        blockchain_count=blockchain_count,
        version=current_app.config["APP_VERSION"],
    )


@main.route("/last_update", methods=["GET"])
def last_update():
    address = request.args.get("address")
    primary = normalize_address(address)  # Address(address)
    if primary is None:
        data = {"last_transaction_timestamp": 0, "update_import_needed": False}
    else:
        user = User(primary)
        update_import_needed = False
        try:
            last = _last_update_inner(user)
            data_version = float(user.get_info("data_version"))
            log("version comp", data_version, user.version)
            if user.version - data_version >= 0.1:
                update_import_needed = True
        except:
            last = user.last_db_modification_timestamp
            update_import_needed = True
        data = {"last_transaction_timestamp": last, "update_import_needed": update_import_needed}
    data = json.dumps(data)
    return data


def _last_update_inner(user):
    query = "SELECT max(last_update) FROM user_addresses WHERE address='" + user.address + "'"
    rows = user.db.select(query)
    log("last_update_inner", rows)
    if len(rows) == 0 or rows[0][0] is None:
        return 0
    return int(rows[0][0])


@main.route("/process", methods=["GET"])
def process():
    primary = normalize_address(request.args.get("address"))
    import_addresses = request.args.get("import_addresses")
    log("import_addresses provided", import_addresses)
    ac_str = request.args.get("ac_str")
    log("ac_str", ac_str)

    redis = Redis(primary)
    if not redis.is_running():
        t = threading.Thread(
            target=_do_process,
            args=(primary, import_addresses, ac_str, redis, current_app.app_context()),
        )
        t.start()
        js = {"phase": "Starting", "pb": 0}
    else:
        pb = ProgressBar(redis)
        phase, progress = pb.retrieve()
        if progress is None:
            progress = 0
            phase = "Starting"
        js = {"phase": phase, "pb": float(progress)}
    return json.dumps(js)


@main.route("/process_data", methods=["GET"])
def process_data():
    primary = normalize_address(request.args.get("address"))
    return _recreate_data_from_caches(primary)


def _do_process(primary, import_addresses, ac_str, redis, app_context):
    app_context.push()
    redis.start()

    active_address = None
    pb = None
    try:
        user = User(primary, do_logging=False)
        all_previous_addresses = list(user.all_addresses.keys())
        log("all_previous_addresses 1", all_previous_addresses)

        all_chains = {}
        for chain_name in Chain.list():
            chain = user.chain_factory(chain_name)
            all_chains[chain_name] = {
                "chain": chain,
                "import_addresses": [],
                "display_addresses": set(),
                "is_upload": False,
            }

        if "my account" in all_previous_addresses:  # uploads
            for chain_name in user.all_addresses["my account"]:
                chain = user.chain_factory(chain_name, is_upload=True)
                all_chains[chain_name] = {
                    "chain": chain,
                    "import_addresses": [],
                    "display_addresses": set(),
                    "is_upload": True,
                }

        log("all chains", all_chains)

        if import_addresses is not None and import_addresses != "":
            if import_addresses == "all":
                if len(all_previous_addresses) == 0:
                    import_addresses = [primary]
                else:
                    import_addresses = all_previous_addresses
            else:
                import_addresses = import_addresses.split(",")
        elif len(all_previous_addresses) == 0:
            import_addresses = [primary]
        else:
            import_addresses = []
        log("import_addresses processed", import_addresses)

        use_previous = True
        try:
            if ac_str is not None and ac_str != "":
                ac_spl = ac_str.split(",")
                for entry in ac_spl:
                    chain_name, address = entry.split(":")
                    all_chains[chain_name]["display_addresses"].add(normalize_address(address))
                use_previous = False
        except:
            pass

        if use_previous:
            for address in user.all_addresses:
                for chain_name in user.all_addresses[address]:
                    if user.all_addresses[address][chain_name]["used"]:
                        all_chains[chain_name]["display_addresses"].add(address)

        for address in import_addresses:
            address = normalize_address(address)
            if address not in all_previous_addresses:
                all_previous_addresses.append(address)

            for chain_name, chain_data in all_chains.items():
                chain = chain_data["chain"]
                if chain.check_validity(address):
                    chain_data["display_addresses"].add(address)

        all_display_addresses = set()
        for chain_name, chain_data in all_chains.items():
            chain_data["display_addresses"] = list(chain_data["display_addresses"])
            log("display addresses for", chain_name, chain_data["display_addresses"])
            for address in chain_data["display_addresses"]:
                if address not in import_addresses and address not in all_previous_addresses:
                    import_addresses.append(address)
                all_display_addresses.add(address)
        all_display_addresses = list(all_display_addresses)

        log("all_previous_addresses 2", all_previous_addresses)
        if "my account" in import_addresses:
            import_addresses.remove("my account")
        log("import_addresses", import_addresses)
        log("all_chains", all_chains)

        import_new = len(import_addresses) > 0

        S = Signatures()

        pb = ProgressBar(redis)
        pb.set("Starting", 0)

        user.get_custom_rates()
        non_fatal_errors = set()

        use_derived = False
        force_forget_derived = user.check_info("force_forget_derived")
        log("force_forget_derived", force_forget_derived)
        if import_new:
            user.set_info("data_version", user.version)
            user.start_import(all_chains)

            redis.enq()
            redis.wait_queue()

            pb.update("Updating FIAT rates", 0.1)
            user.fiat_rates.download_all_rates()

            for chain_name, chain_data in all_chains.items():
                chain = chain_data["chain"]
                chain_data["addresses_to_check"] = (
                    {}
                )  # going to send a request to scanner for each address in here

                for active_address in import_addresses:
                    active_address = normalize_address(active_address)
                    if not chain.is_upload and not chain.check_validity(active_address):
                        continue

                    present = user.check_address_present(active_address, chain_name)
                    if present:
                        user.set_address_used(active_address, chain_name)
                        chain_data["import_addresses"].append(active_address)
                    else:
                        chain_data["addresses_to_check"][active_address] = False

            # called in threads, to check in parallel against all scanners
            def check_chain_for_addresses(chain_data, app_context):
                app_context.push()
                chain = chain_data["chain"]
                address_dict = chain_data["addresses_to_check"]
                for active_address in address_dict.keys():
                    try:
                        log("checking address present on chain", chain.name, active_address)
                        present = chain.check_presence(active_address)
                        log(
                            "checked address present on chain",
                            chain.name,
                            active_address,
                            "present?",
                            present,
                        )
                        if present:
                            address_dict[active_address] = True
                    except:
                        user.current_import.add_error(
                            Import.PRESENCE_CHECK_FAILURE,
                            chain=chain,
                            address=active_address,
                            debug_info=traceback.format_exc(),
                        )
                        log(
                            "failed to check chain",
                            chain.name,
                            "for address",
                            active_address,
                            traceback.format_exc(),
                        )
                        chain_data["failure"] = True
                        return

            pb.update("Checking supported chains for your addresses")
            threads = []
            for chain_name, chain_data in all_chains.items():
                if not chain_data["is_upload"] and len(chain_data["addresses_to_check"]) > 0:
                    t = threading.Thread(
                        target=check_chain_for_addresses,
                        args=(chain_data, current_app.app_context()),
                    )
                    threads.append(t)
                    t.start()

            joined_cnt = 0
            for t in threads:
                t.join()
                joined_cnt += 1
                pb.update(
                    "Checking supported chains for your addresses: "
                    + str(joined_cnt)
                    + "/"
                    + str(len(threads)),
                    5.0 / len(threads),
                )

            for chain_name, chain_data in all_chains.items():
                chain = chain_data["chain"]
                chain.progress_bar = pb
                if "failure" in chain_data:

                    err = (
                        "We were not able to retrieve transactions from "
                        + chain_name
                        + ", "
                        + chain.domain
                        + " might be down or API non-functional. Transactions from "
                        + chain.name
                        + " may be missing or outdated."
                    )
                    non_fatal_errors.add(err)
                else:
                    for checked_address in chain_data["addresses_to_check"].keys():
                        if chain_data["addresses_to_check"][checked_address]:
                            chain_data["import_addresses"].append(checked_address)
                            user.set_address_present(checked_address, chain_name)
                            user.set_address_used(checked_address, chain_name)

                log("import addresses per chain", chain_name, chain_data["import_addresses"])
        else:
            previous_use = set()
            for address in user.all_addresses:
                for chain_name in user.all_addresses[address]:
                    if user.all_addresses[address][chain_name]["used"]:
                        previous_use.add(chain_name + ":" + address)
                        user.set_address_used(address, chain_name, value=0)  # unset all address use

            current_use = set()
            for chain_name, chain_data in all_chains.items():
                for address in chain_data["display_addresses"]:
                    current_use.add(chain_name + ":" + address)
                    user.set_address_used(address, chain_name)  # set current address use

            if not force_forget_derived:
                log("comparing previous use vs current use", str(previous_use), str(current_use))
                rows = user.db.select("SELECT id FROM transactions_derived LIMIT 1")
                if previous_use == current_use and len(rows) > 0:
                    use_derived = True

        log("import_new", import_new)
        log("use_derived", use_derived)

        total_request_count = 0
        total_request_count_disp = 0
        for chain_name, chain_data in all_chains.items():
            chain = chain_data["chain"]
            if chain.is_upload or chain.discontinued:
                continue

            addresses = chain_data["import_addresses"]
            for active_address in addresses:
                if chain.check_validity(active_address):
                    total_request_count += 1

            disp_addresses = list(chain_data["display_addresses"])
            for active_address in disp_addresses:
                if chain.check_validity(active_address):
                    total_request_count_disp += 1
        log("total_request_count", total_request_count, total_request_count_disp)

        if import_new or not use_derived:
            C = Coingecko(verbose=True)
            C.make_contracts_map()

        if import_new:
            pb.set("Importing transactions", 5)
            try:
                redis.cleanup()
            except:
                log_error("EXCEPTION trying to cleanup redis", primary)

            user.current_import.populate_addresses(user, all_chains)

            def threaded_transaction_processing(chain_data, app_context):
                app_context.push()
                addresses = chain_data["import_addresses"]
                chain = chain_data["chain"]
                for active_address in addresses:
                    active_address = normalize_address(active_address)
                    log("checking validity", chain.name, active_address)
                    if chain.check_validity(active_address):
                        log("is valid")
                        try:
                            transactions = chain.get_transactions(
                                user, active_address, 28.0 / total_request_count
                            )
                        except:
                            log_error(
                                "FAILED TO GET TRANSACTIONS FROM "
                                + chain.name
                                + " FOR ADDRESS "
                                + active_address
                            )
                            user.current_import.add_error(
                                Import.UNKNOWN_ERROR,
                                chain=chain,
                                address=active_address,
                                debug_info=traceback.format_exc(),
                            )
                            continue
                        log("retrieved transactions", chain.name, active_address, len(transactions))
                        chain.correct_transactions(
                            active_address, transactions, 2.0 / total_request_count
                        )
                        current_tokens = chain.get_current_tokens(active_address)
                        for txhash, transaction in transactions.items():
                            log("txhash proc", txhash)
                            if txhash not in chain_data["transactions"]:
                                chain_data["transactions"][txhash] = transaction
                            else:
                                chain.merge_transaction(
                                    transaction, chain_data["transactions"][txhash]
                                )

                        if current_tokens is not None:
                            chain_data["current_tokens"][active_address] = current_tokens
                            log(
                                "populated current_tokens",
                                chain.name,
                                active_address,
                                len(current_tokens),
                                filename="solana.txt",
                            )
                        else:
                            log("populated current_tokens - NONE!", chain.name, active_address)

            def threaded_covalent(all_chains, app_context):
                app_context.push()
                rq_cnt = 0
                for chain_name, chain_data in all_chains.items():
                    if (
                        not chain_data["is_upload"]
                        and "covalent_mapping" in Chain.CONFIG[chain_name]
                    ):
                        rq_cnt += len(chain_data["import_addresses"])

                if rq_cnt > 0:
                    for chain_name, chain_data in all_chains.items():
                        chain = chain_data["chain"]
                        if chain.is_upload:
                            continue
                        chain.covalent_download(chain_data, pb_alloc=5 / float(rq_cnt))

            t_covalent = threading.Thread(
                target=threaded_covalent, args=(all_chains, current_app.app_context())
            )  # this asshole is the longest
            t_covalent.start()

            threads = []
            user.load_solana_nfts()

            for chain_name, chain_data in all_chains.items():
                chain_data["transactions"] = {}
                chain_data["current_tokens"] = {}
                if len(chain_data["import_addresses"]) > 0 and not chain_data["is_upload"]:
                    log("calling threaded_transaction_processing", chain_name)
                    t = threading.Thread(
                        target=threaded_transaction_processing,
                        args=(chain_data, current_app.app_context()),
                    )
                    threads.append(t)
                    t.start()

            joined_cnt = 0
            for t in threads:
                t.join()
                joined_cnt += 1

            def threaded_balances(all_chains, app_context):
                app_context.push()
                user.get_thirdparty_data(all_chains, progress_bar=pb)  # alloc 5

            t_balances = threading.Thread(
                target=threaded_balances, args=(all_chains, current_app.app_context())
            )
            t_balances.start()

            t_balances.join()
            t_covalent.join()

            for chain_name, chain_data in all_chains.items():
                chain = chain_data["chain"]
                if chain.is_upload:
                    continue
                chain.covalent_correction(chain_data)
                chain.balance_provider_correction(chain_data)

            pb.update("Loading coingecko symbols", 0)
            try:
                C.download_symbols_to_db(drop=True, progress_bar=pb)  # alloc 3
            except:
                log_error("Failed to download coingecko symbols", primary)

            pb.update("Storing transactions,", 0)

            for chain_name, chain_data in all_chains.items():
                user.store_transactions(
                    chain_data["chain"],
                    chain_data["transactions"],
                    chain_data["import_addresses"],
                    C,
                )
                log("storing transactions", chain_name, len(chain_data["transactions"]))
                user.store_current_tokens(chain_data["chain"], chain_data["current_tokens"])

                for active_address in chain_data["import_addresses"]:
                    active_address = normalize_address(active_address)
                    user.set_address_update(active_address, chain_name)

            user.store_solana_nfts()

        pb.set("Loading transactions from database", 50)

        user.load_addresses()
        user.load_tx_counts()
        if import_new or not use_derived:

            pb.update("Loading transactions")
            transactions, _ = user.load_transactions(all_chains, load_derived=True)
            log("loaded transactions", len(transactions), filename="derived.txt")
            pb.update("Loading known counterparties")
            contract_dict, counterparty_by_chain, input_list = user.get_contracts(transactions)

            address_db = SQLite("addresses", read_only=True)
            for chain_name, chain_data in all_chains.items():
                if not chain_data["is_upload"] and len(chain_data["display_addresses"]):
                    pb.update("Loading known counterparties for " + chain_name)
                    chain_data["chain"].init_addresses(
                        address_db, counterparty_by_chain[chain_name]
                    )
            address_db.disconnect()

            pb.set("Looking up unknown counterparties")
            if total_request_count == 0:
                total_request_count = total_request_count_disp

            def threaded_update_progenitors(
                chain_name, chain_data, filtered_counterparty_list, app_context
            ):
                app_context.push()
                chain = chain_data["chain"]
                try:
                    chain_db_writes = chain.update_progenitors(
                        filtered_counterparty_list, 10.0 / total_request_count
                    )  # alloc 10
                    chain_data["progenitor_db_writes"] = chain_db_writes
                    log(
                        "new writes",
                        chain_name,
                        len(chain_db_writes),
                        filename="address_update.txt",
                    )
                except:
                    log_error(
                        "error updating progenitors", primary, chain_name, traceback.format_exc()
                    )

            threads = []
            for chain_name, chain_data in all_chains.items():
                chain = chain_data["chain"]
                if not chain.is_upload and isinstance(chain.api, (EtherscanV1Api, EtherscanV2Api)):
                    filtered_counterparty_list = chain.filter_progenitors(
                        list(counterparty_by_chain[chain_name])
                    )
                    log(
                        "filtered_counterparty_list",
                        chain_name,
                        filtered_counterparty_list,
                        filename="address_update.txt",
                    )
                    if len(filtered_counterparty_list) > 0:
                        t = threading.Thread(
                            target=threaded_update_progenitors,
                            args=(
                                chain_name,
                                chain_data,
                                filtered_counterparty_list,
                                current_app.app_context(),
                            ),
                        )
                        threads.append(t)
                        t.start()

            joined_cnt = 0
            for t in threads:
                t.join()
                joined_cnt += 1

            all_db_writes = []
            for chain_name, chain_data in all_chains.items():
                if "progenitor_db_writes" in chain_data:
                    all_db_writes.extend(chain_data["progenitor_db_writes"])

            if all_db_writes:
                insert_cnt = 0
                address_db = SQLite("addresses")
                for write in all_db_writes:
                    chain_name, values = write
                    cn = chain_name.upper().replace(" ", "_")
                    entity = values[-2]
                    address_to_add = values[0]
                    rc = address_db.insert_kw(
                        cn + "_addresses", values=values, ignore=(entity == "unknown")
                    )
                    if rc > 0:
                        address_db.insert_kw(
                            cn + "_labels", values=[address_to_add, "auto"], ignore=True
                        )
                        insert_cnt += 1
                if insert_cnt > 0:
                    address_db.commit()
                    log("New addresses added", insert_cnt, filename="address_lookups.txt")
                address_db.disconnect()

            t = time.time()
            log("contract_dict", contract_dict)
            S.init_from_db(input_list)

            pb.set("Loading coingecko rates", 63)
            needed_token_times = user.get_needed_token_times(transactions)
            log("needed_token_times", needed_token_times)

            C.init_from_db_2(all_chains, needed_token_times, progress_bar=pb)
        else:
            pb.update("Loading transactions")
            transactions, _ = user.load_transactions(all_chains, load_derived=True)
            needed_token_times = user.get_needed_token_times(transactions)
            try:
                C = Coingecko.init_from_cache(user)
                for coingecko_id in needed_token_times:
                    assert coingecko_id in C.rates
            except:
                C = Coingecko(verbose=True)
                pb.set("Loading coingecko symbols", 60)
                try:
                    C.download_symbols_to_db(drop=True, progress_bar=pb)  # alloc 3
                except:
                    log_error("Failed to download coingecko symbols", primary)

                pb.set("Loading coingecko rates", 63)
                C.make_contracts_map()
                C.init_from_db_2(all_chains, needed_token_times, progress_bar=pb)
            S = None

        if import_new:
            user.finish_import()
        current_tokens = user.load_current_tokens(C)
        log("loaded current tokens", current_tokens)

        if import_new:
            redis.deq()

        log("coingecko initialized", C.initialized)
        pb.set("Classifying transactions", 80)
        store_derived = import_new or not use_derived
        if store_derived:
            user.wipe_derived_data()

        transactions_js = user.transactions_to_log(
            C, S, transactions, progress_bar=pb, store_derived=store_derived
        )  # alloc 10
        log("all transactions", transactions_js)

        pb.set("Loading custom types", 90)
        custom_types = user.load_custom_types()

        pb.set("Calculating taxes", 90)
        calculator = Calculator(user, C)
        calculator.process_transactions(transactions_js, user)  # alloc

        # process_transactions affects coingecko rates! Need to cache it after, not before.
        C.dump(user)

        pb.set("Calculating taxes", 95)
        calculator.matchup()
        pb.set("Calculating taxes", 97)
        calculator.cache()

        path = os.path.join(current_app.instance_path, USER_DIRNAME)
        path = os.path.join(path, primary)
        with open(
            os.path.join(path, "transactions.json"), "w", newline="", encoding="utf-8"
        ) as js_file:
            js_file.write(json.dumps(transactions_js, indent=2, sort_keys=True))

        info_fields = [
            "tx_per_page",
            "high_impact_amount",
            "dc_fix_shutup",
            "matchups_visible",
            "fiat",
            "opt_tx_costs",
            "opt_vault_gain",
            "opt_vault_loss",
        ]
        info = {}
        for field in info_fields:
            value = user.get_info(field)
            if value is not None:
                info[field] = value

        non_fatal_errors = non_fatal_errors.union(set(user.load_relevant_errors()))
        data_version = float(user.get_info("data_version"))
        if user.version - data_version >= 0.1:
            non_fatal_errors.add(
                "Software has been updated since your previous import. "
                "We recommend importing new transactions to enable all the features."
            )

        user.load_import_versions()

        data = {
            "info": info,
            "transactions": transactions_js,
            "custom_types": custom_types,
            "CA_long": calculator.CA_long,
            "CA_short": calculator.CA_short,
            "CA_errors": calculator.errors,
            "incomes": calculator.incomes,
            "interest": calculator.interest_payments,
            "expenses": calculator.business_expenses,
            "vaults": calculator.vaults_json(),
            "loans": calculator.loans_json(),
            "tokens": calculator.tokens_json(),
            "non_fatal_errors": list(non_fatal_errors),
            "latest_tokens": current_tokens,
            "fiat_info": Twelve.FIAT_SYMBOLS,
            "all_address_info": user.all_addresses,
            "chain_config": Chain.config_json(),
            "version": {"software": user.version, "data": data_version},
        }

        pb.set("Uploading to your browser", 98)
        user.done()

        to_empty_in_cache = [
            "transactions",
            "CA_long",
            "CA_short",
            "CA_errors",
            "incomes",
            "interest",
            "vaults",
            "loans",
            "tokens",
        ]
        for entry in to_empty_in_cache:
            data[entry] = ""
    except:
        log("EXCEPTION in process", primary, active_address, traceback.format_exc())
        log_error("EXCEPTION in process", primary, active_address)
        data = {
            "error": "An error has occurred while processing transactions. "
            "Please let us know on Discord if you received this message."
        }

    path = os.path.join(current_app.instance_path, USER_DIRNAME)
    path = os.path.join(path, primary)
    with open(os.path.join(path, "data_cache.json"), "w", newline="", encoding="utf-8") as js_file:
        js_file.write(json.dumps(data, indent=2, sort_keys=True))

    if pb is not None:
        pb.set("Uploading to your browser", 100)
    redis.finish()


def _recreate_data_from_caches(primary):
    path = os.path.join(current_app.instance_path, USER_DIRNAME)
    path = os.path.join(path, primary)
    with open(os.path.join(path, "data_cache.json"), "r", encoding="utf-8") as js_file:
        js = js_file.read()

    data = json.loads(js)
    if "error" not in data:
        with open(os.path.join(path, "transactions.json"), "r", encoding="utf-8") as js_file:
            js = js_file.read()

        data["transactions"] = json.loads(js)
        user = User(primary)

        calculator = Calculator(user, None)
        calculator.from_cache()
        data["CA_long"] = calculator.CA_long
        data["CA_short"] = calculator.CA_short
        data["CA_errors"] = calculator.errors
        data["incomes"] = calculator.incomes
        data["interest"] = calculator.interest_payments
        data["expenses"] = calculator.business_expenses
        data["vaults"] = calculator.vaults_json()
        data["loans"] = calculator.loans_json()
        data["tokens"] = calculator.tokens_json()
    data = json.dumps(data)
    return data


@main.route("/save_custom_val", methods=["POST"])
def save_custom_val():
    address = normalize_address(request.args.get("address"))
    try:
        form = request.form
        transfer_id_str = form["transfer_id"]
        transaction = form["transaction"]
        prop = form["prop"]
        val = form["val"]

        log(
            "apply_custom_val",
            address,
            transaction,
            transfer_id_str,
            prop,
            val,
        )
        user = User(address)
        user.save_custom_val(transaction, transfer_id_str, prop, val)
        user.done()
        js = {"success": 1}
    except:
        log("EXCEPTION in save_custom_val", traceback.format_exc())
        log_error("EXCEPTION in save_custom_val", address, request.args, request.form)
        js = {"error": "An error has occurred while saving custom value"}
    data = json.dumps(js)
    return data


@main.route("/undo_custom_changes", methods=["POST"])
def undo_custom_changes():
    address = normalize_address(request.args.get("address"))

    try:
        form = request.form
        transaction = form["transaction"]

        log("undo_custom_changes", address, transaction)
        user = User(address)
        user.get_custom_rates()
        transaction_js = user.undo_custom_changes(transaction)
        js = {"success": 1, "transactions": [transaction_js]}
        user.done()
    except:
        log("EXCEPTION in undo_custom_changes", traceback.format_exc())
        log_error("EXCEPTION in undo_custom_changes", address, request.args, request.form)
        js = {"error": "An error has occurred while undoing custom changes"}
    data = json.dumps(js)
    return data


@main.route("/recolor", methods=["POST"])
def recolor():
    t = time.time()
    address = normalize_address(request.args.get("address"))
    try:
        form = request.form

        color_id = form["color_id"]
        transactions = form["transactions"]

        log("recolor", address, color_id, transactions)
        log("recolor timing 1", time.time() - t)
        user = User(address)
        log("recolor timing 2", time.time() - t)
        user.recolor(color_id, transactions.split(","))
        log("recolor timing 3", time.time() - t)
        user.done()
        log("recolor timing 4", time.time() - t)
        js = {"success": 1}
    except:
        log("EXCEPTION in recolor", traceback.format_exc())
        log_error("EXCEPTION in recolor", address, request.args, request.form)
        js = {"error": "An error has occurred while recoloring"}
    data = json.dumps(js)
    return data


@main.route("/save_note", methods=["POST"])
def save_note():
    address = normalize_address(request.args.get("address"))
    try:
        form = request.form
        note = form["note"]
        txid = request.args.get("transaction")

        log("save_note", address, txid, note)
        user = User(address)
        user.save_note(note, txid)
        user.done()
        js = {"success": 1}
    except:
        log("EXCEPTION in save_note", traceback.format_exc())
        log_error("EXCEPTION in save_note", address, request.args, request.form)
        js = {"error": "An error has occurred while saving note"}
    data = json.dumps(js)
    return data


@main.route("/progress_bar", methods=["GET"])
def get_progress_bar():
    address = normalize_address(request.args.get("address"))
    try:
        redis = Redis(address)
        pb = ProgressBar(redis)

        phase, progress = pb.retrieve()
        if progress is None:
            progress = 0
            phase = "Starting"
        js = {"phase": phase, "pb": float(progress)}
    except:
        log("EXCEPTION in progress_bar", traceback.format_exc())
        log_error("EXCEPTION in progress_bar", address)
        js = {"phase": "Progressbar error", "pb": 100}

    return json.dumps(js)


@main.route("/update_progenitors", methods=["GET"])
def update_progenitors():
    address = request.args.get("user")
    chain_name = request.args.get("chain")
    try:
        progenitor = request.args.get("progenitor")
        counterparty = request.args.get("counterparty")
        if (len(address) == 42) or chain_name == "Solana":
            counterparty = html.escape(counterparty[:30])
            user = User(address)
            db = user.db
            db.insert_kw("custom_names", values=[chain_name, progenitor.lower(), counterparty])
            db.commit()
            db.disconnect()
        js = {"success": "true"}
    except:
        log("EXCEPTION in update_progenitors", traceback.format_exc())
        log_error("EXCEPTION in update_progenitors", address, request.args)
        js = {"error": "An error has occurred while updating counterparty"}
    return json.dumps(js)


@main.route("/save_info", methods=["GET"])
def save_info():
    address = normalize_address(request.args.get("address"))
    try:
        user = User(address)
        field = request.args.get("field")
        value = request.args.get("value")
        assert field in ["tx_per_page", "high_impact_amount", "dc_fix_shutup", "matchups_visible"]
        user.set_info(field, value)
        user.done()
        js = {"success": 1}
    except:
        log("EXCEPTION in save_info", traceback.format_exc())
        log_error("EXCEPTION in save_info", address, request.args)
        js = {"error": "An error has occurred while saving information"}
    data = json.dumps(js)
    return data


@main.route("/minmax_transactions", methods=["POST"])
def minmax_transactions():
    address = normalize_address(request.args.get("address"))
    try:
        form = request.form
        minimized = form["minimized"]
        transactions = form["transactions"]

        log("minmax_transaction", address, minimized, transactions)
        user = User(address)
        user.db.do_logging = True
        user.db.update_kw("transactions", "id IN " + sql_in(transactions), minimized=minimized)
        user.db.commit()
        user.done()
        js = {"success": 1}
    except:
        log("EXCEPTION in minmax_transaction", traceback.format_exc())
        log_error("EXCEPTION in minmax_transaction", address, request.args)
        js = {"error": "An error has occurred while saving information"}
    data = json.dumps(js)
    return data


@main.route("/delete_address", methods=["POST"])
def delete_address():
    address = normalize_address(request.args.get("address"))
    try:
        form = request.form
        address_to_delete = form["address_to_delete"]
        log("delete address", address, address_to_delete)

        user = User(address)
        need_reproc = user.delete_address(address_to_delete)
        if need_reproc:
            user.set_info("force_forget_derived", 1)
        user.load_addresses()
        user.load_tx_counts()
        user.done()
        js = {"success": 1, "all_address_info": user.all_addresses, "reproc_needed": need_reproc}
    except:
        log("EXCEPTION in delete_address", traceback.format_exc())
        log_error("EXCEPTION in delete_address", address, request.args, request.form)
        js = {"error": "An error has occurred while deleting an address"}
    data = json.dumps(js)
    return data


@main.route("/update_coingecko_id", methods=["GET"])
def update_coingecko_id():
    address = normalize_address(request.args.get("address"))
    redis = Redis(address)
    redis.start()
    pb = ProgressBar(redis)
    pb.set("Starting", 0)
    try:
        chain_name = request.args.get("chain")
        contract = request.args.get("contract")
        new_id = request.args.get("new_id")

        user = User(address)
        C = Coingecko.init_from_cache(user)
        C.make_contracts_map()
        error, transactions_js = user.update_coingecko_id(chain_name, contract, new_id, C, pb)
        user.done()
        if error is None:
            js = {"success": 1, "transactions": transactions_js}
        else:
            js = {"error": error}
    except:
        log_error("EXCEPTION in update_coingecko_id", address, request.args)
        js = {"error": "An error has occurred while updating coingecko ID"}
    pb.set("Uploading to your browser", 100)
    redis.finish()
    data = json.dumps(js)
    return data
