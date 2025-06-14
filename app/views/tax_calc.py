import json
import os
import traceback

from flask import Blueprint, current_app, request, send_file

from ..coingecko import Coingecko
from ..constants import USER_DIRNAME
from ..tax_calc import Calculator
from ..user import User
from ..util import log, log_error, normalize_address

tax_calc = Blueprint("tax_calc", __name__)


@tax_calc.route("/calc_tax", methods=["POST"])
def calc_tax():
    address = normalize_address(request.args.get("address"))
    try:
        mtm = request.args.get("mtm")
        if mtm == "false":
            mtm = False
        else:
            mtm = True

        data = request.get_json()
        transactions_js = json.loads(data)
        log("all transactions", transactions_js)

        user = User(address)
        user.get_custom_rates()
        C = Coingecko.init_from_cache(user)

        calculator = Calculator(user, C, mtm=mtm)
        calculator.process_transactions(transactions_js, user)
        calculator.matchup()
        calculator.cache()

        js = {
            "CA_long": calculator.CA_long,
            "CA_short": calculator.CA_short,
            "CA_errors": calculator.errors,
            "incomes": calculator.incomes,
            "interest": calculator.interest_payments,
            "expenses": calculator.business_expenses,
            "vaults": calculator.vaults_json(),
            "loans": calculator.loans_json(),
            "tokens": calculator.tokens_json(),
        }

        user.done()
    except:
        log("EXCEPTION in calc_tax", traceback.format_exc())
        log_error("EXCEPTION in calc_tax", address, request.args)
        js = {"error": "An error has occurred while calculating taxes"}
    data = json.dumps(js)
    return data


@tax_calc.route("/download", methods=["GET"])
def download():
    address = normalize_address(request.args.get("address"))
    try:
        dl_type = request.args.get("type")
        path = os.path.join(current_app.instance_path, USER_DIRNAME)
        path = os.path.join(path, address)

        if dl_type == "transactions_json":
            return send_file(os.path.join(path, "transactions.json"), as_attachment=True, max_age=0)

        if dl_type == "transactions_csv":
            user = User(address)
            user.json_to_csv()
            user.done()
            return send_file(os.path.join(path, "transactions.csv"), as_attachment=True, max_age=0)

        if dl_type == "tax_forms":
            year = request.args.get("year")
            user = User(address)
            C = Coingecko.init_from_cache(user)
            calculator = Calculator(user, C)
            calculator.from_cache()

            calculator.make_forms(year)
            user.done()
            return send_file(
                os.path.join(path, f"tax_forms_{year}.zip"), as_attachment=True, max_age=0
            )

        if dl_type == "turbotax":
            year = request.args.get("year")
            user = User(address)
            C = Coingecko.init_from_cache(user)
            calculator = Calculator(user, C)
            calculator.from_cache()

            batched = calculator.make_turbotax(year)
            user.done()
            if batched:
                return send_file(
                    os.path.join(path, f"turbotax_8949_{year}.zip"), as_attachment=True, max_age=0
                )
            return send_file(
                os.path.join(path, f"turbotax_8949_{year}.csv"), as_attachment=True, max_age=0
            )
    except:
        log_error("EXCEPTION in download", address, request.args)
        log("EXCEPTION in download", traceback.format_exc())
        return "EXCEPTION " + str(traceback.format_exc())
    return None


@tax_calc.route("/save_js", methods=["POST"])
def save_js():
    address = normalize_address(request.args.get("address"))
    path = os.path.join(current_app.instance_path, USER_DIRNAME)
    path = os.path.join(path, address)
    try:
        data = request.get_json()
        transactions_js = json.loads(data)
        with open(
            os.path.join(path, "transactions.json"), "w", newline="", encoding="utf-8"
        ) as js_file:
            js_file.write(json.dumps(transactions_js, indent=2, sort_keys=True))
        js = {"success": 1}

    except:
        log("EXCEPTION in download_current", traceback.format_exc())
        log_error("EXCEPTION in download_current", address, request.args)
        js = {"error": "An error has occurred while downloading a file"}
    data = json.dumps(js)
    return data


@tax_calc.route("/save_options", methods=["POST"])
def save_options():
    address = normalize_address(request.args.get("address"))
    try:
        form = request.form
        recalc_needed = False
        reproc_needed = False

        fiat = form["opt_fiat"]
        adjust_custom = False
        if "opt_fiat_update_custom" in form:
            adjust_custom = form["opt_fiat_update_custom"] in ["on", "checked"]
        log("adjust_custom", adjust_custom)

        js = {}
        user = User(address)
        if fiat != user.fiat:
            reproc_needed = True
            user.load_fiat()
            user.set_info("fiat", fiat)
            js["fiat"] = fiat
            if adjust_custom:
                user.adjust_custom_rates(fiat)

        radio_options = ["tx_costs", "vault_gain", "vault_loss"]
        for opt in radio_options:
            opt_code = "opt_" + opt
            if opt_code in form:
                current_val = user.get_info(opt_code)
                new_val = form[opt_code]
                log("opt", opt_code, current_val, new_val)
                if current_val != new_val:
                    js[opt_code] = new_val
                    user.set_info(opt_code, new_val)
                    recalc_needed = True

        user.done()
        js.update({"success": 1, "reproc_needed": reproc_needed, "recalc_needed": recalc_needed})
    except:
        log("EXCEPTION in save_options", traceback.format_exc())
        log_error("EXCEPTION in save_options", address, request.args)
        js = {"error": "An error has occurred while saving options"}
    data = json.dumps(js)
    return data
