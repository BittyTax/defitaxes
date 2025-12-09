import io
import json
import os
import traceback
from contextlib import redirect_stderr

from bittytax.config import config as bt_config
from bittytax.conv.datafile import DataFile
from bittytax.conv.output_excel import OutputExcel
from bittytax.conv.parsers.defitaxes import DtConfig, DtTransferMapping, defitaxes_parser
from flask import Blueprint, current_app, request, send_file

from ..coingecko import CoinGecko
from ..constants import USER_DIRNAME
from ..tax_calc import Calculator
from ..user import User
from ..user_config import UserConfig
from ..util import convert_ansi_to_html, log, log_error, normalize_address

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
        cg = CoinGecko.init_from_cache(user)

        calculator = Calculator(user, cg, mtm=mtm)
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

        if dl_type == "bittytax_xlsx":
            redis_client = current_app.extensions["redis_binary"]
            redis_prefix = current_app.config["REDIS_PREFIX"]
            redis_key = f"{redis_prefix}:bittytax_excel_{address}"
            excel_data = redis_client.get(redis_key)

            if not excel_data:
                current_app.logger.warning(
                    f"No BittyTax Excel file found in Redis for address {address}"
                )
                return (
                    "BittyTax file not exported or has expired. Please export the file again.",
                    400,
                )

            bi = io.BytesIO(excel_data)
            redis_client.delete(redis_key)
            current_app.logger.info(
                f"Retrieved and deleted BittyTax Excel file from Redis for address {address}"
            )

            return send_file(
                bi,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=f"BittyTax_Records_{address}.xlsx",
                max_age=0,
            )

        if dl_type == "tax_forms":
            year = request.args.get("year")
            user = User(address)
            cg = CoinGecko.init_from_cache(user)
            calculator = Calculator(user, cg)
            calculator.from_cache()

            calculator.make_forms(year)
            user.done()
            return send_file(
                os.path.join(path, f"tax_forms_{year}.zip"), as_attachment=True, max_age=0
            )

        if dl_type == "turbotax":
            year = request.args.get("year")
            user = User(address)
            cg = CoinGecko.init_from_cache(user)
            calculator = Calculator(user, cg)
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


@tax_calc.route("/process_bittytax", methods=["POST"])
def process_bittytax():
    address = normalize_address(request.args.get("address"))
    try:
        currency = request.args.get("currency", "USD")
        bt_config.ccy = currency

        transfer_in_known = int(request.args.get("transfer_in_known", "0"))
        transfer_in_unknown = int(request.args.get("transfer_in_unknown", "0"))
        transfer_out_known = int(request.args.get("transfer_out_known", "0"))
        transfer_out_unknown = int(request.args.get("transfer_out_unknown", "0"))

        username = request.headers.get("X-Remote-User")
        if username:
            try:
                user_config = UserConfig(username)
                user_config.save_settings(
                    transfer_in_known,
                    transfer_in_unknown,
                    transfer_out_known,
                    transfer_out_unknown,
                    currency,
                )
            except Exception as e:
                current_app.logger.error(f"Error saving user config for {username}, {e}")

        dt_config = DtConfig(
            transfer_in_known=DtTransferMapping(transfer_in_known),
            transfer_in_unknown=DtTransferMapping(transfer_in_unknown),
            transfer_out_known=DtTransferMapping(transfer_out_known),
            transfer_out_unknown=DtTransferMapping(transfer_out_unknown),
        )

        user = User(address)
        rows = user.get_csv_data()

        def row_to_strings(row):
            result = []
            for value in row:
                if value is None:
                    result.append("")
                elif not isinstance(value, str):
                    result.append(str(value))
                else:
                    result.append(value)
            return result

        data_file = DataFile(defitaxes_parser, [row_to_strings(row) for row in rows])

        stderr_capture = io.StringIO()
        with redirect_stderr(stderr_capture):
            data_file.parse(dt_config=dt_config)

        parse_output = stderr_capture.getvalue()
        if parse_output:
            parse_output = convert_ansi_to_html(parse_output)

        user.done()

        bi = io.BytesIO()
        output_excel = OutputExcel("BittyTax", [data_file], stream=bi)
        output_excel.write_excel()
        bi.seek(0)

        redis_client = current_app.extensions["redis_binary"]
        redis_prefix = current_app.config["REDIS_PREFIX"]
        redis_key = f"{redis_prefix}:bittytax_excel_{address}"
        excel_data = bi.getvalue()
        redis_client.setex(redis_key, 3600, excel_data)
        current_app.logger.info(f"Stored BittyTax Excel file in Redis for address {address}")

        js = {
            "success": True,
            "parse_output": parse_output if parse_output else None,
            "message": "BittyTax export successful",
        }

    except Exception as e:
        log("EXCEPTION in process_bittytax", traceback.format_exc())
        log_error("EXCEPTION in process_bittytax", address, request.args)
        js = {
            "success": False,
            "error": "An error occurred while exporting for BittyTax",
            "details": str(e),
        }

    return json.dumps(js)


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
