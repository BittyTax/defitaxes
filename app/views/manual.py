import json
import traceback

from flask import Blueprint, request

from ..coingecko import Coingecko
from ..user import User
from ..util import log, log_error, normalize_address

manual_transactions = Blueprint("manual_transactions", __name__)


@manual_transactions.route("/save_manual_transaction", methods=["POST"])
def save_manual_transaction():
    address = normalize_address(request.args.get("address"))
    chain_name = request.args.get("chain")

    try:
        form = request.form
        done = False
        idx = 0
        all_tx_blobs = []
        while not done:
            s_idx = str(idx)
            log("form", form)
            try:
                ts = form["mt" + s_idx + "_ts"]
            except:  # out of transactions
                break
            tx_hash = form["mt" + s_idx + "_hash"]
            op = form["mt" + s_idx + "_op"]
            cp = None

            max_tr_disp_idx = int(form["mt" + s_idx + "_tr_disp_idx"])
            transfers = []
            for tr_disp_idx in range(max_tr_disp_idx):
                s_tr_idx = str(tr_disp_idx)
                if "mt" + s_idx + "_from" + s_tr_idx in form:
                    transfers.append(
                        [
                            form["mt" + s_idx + "_transfer_id" + s_tr_idx],
                            form["mt" + s_idx + "_from" + s_tr_idx],
                            form["mt" + s_idx + "_to" + s_tr_idx],
                            form["mt" + s_idx + "_what" + s_tr_idx],
                            form["mt" + s_idx + "_amount" + s_tr_idx],
                            form["mt" + s_idx + "_nft_id" + s_tr_idx],
                        ]
                    )
                    if (
                        form["mt" + s_idx + "_from" + s_tr_idx] == "my account"
                        or form["mt" + s_idx + "_to" + s_tr_idx] == "my account"
                    ):
                        raise RuntimeError('Using "my account" is not allowed')

            txid = None
            if "mt" + s_idx + "_txid" in form:
                txid = form["mt" + s_idx + "_txid"]
            tx_blob = [ts, tx_hash, op, cp, transfers, txid]
            all_tx_blobs.append(tx_blob)
            idx += 1

        user = User(address)
        C = Coingecko.init_from_cache(user)
        transactions_js = user.save_manual_transactions(chain_name, address, all_tx_blobs, C)
        user.done()
        js = {"success": 1, "transactions": transactions_js}
    except:
        log("EXCEPTION in save_manual_transaction", traceback.format_exc())
        log_error("EXCEPTION in save_manual_transaction", address, request.args, request.form)
        js = {"error": "An error has occurred while saving manual transaction"}
    data = json.dumps(js)
    return data


@manual_transactions.route("/delete_manual_transaction", methods=["POST"])
def delete_manual_transaction():
    address = normalize_address(request.args.get("address"))
    try:
        form = request.form
        txid = form["txid"]
        log("delete manual transaction", address, txid)
        user = User(address)
        user.delete_manual_transaction(txid)
        user.done()
        js = {"success": 1}
    except:
        log("EXCEPTION in delete_manual_transaction", traceback.format_exc())
        log_error("EXCEPTION in delete_manual_transaction", address, request.args, request.form)
        js = {"error": "An error has occurred while deleting a transaction"}
    data = json.dumps(js)
    return data
