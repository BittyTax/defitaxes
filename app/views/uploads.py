# -*- coding: utf-8 -*-
import json
import traceback

from flask import Blueprint, request

from ..coingecko import Coingecko
from ..redis_wrap import Redis, ProgressBar
from ..user import User
from ..util import log, log_error, normalize_address, persist

uploads = Blueprint("uploads", __name__)


@uploads.route("/upload_csv", methods=["GET", "POST"])
def upload_csv():
    address = normalize_address(request.args.get("address"))
    persist(address)
    redis = Redis(address)
    redis.start()
    pb = ProgressBar(redis)
    pb.set("Starting", 0)
    try:
        source = request.args.get("source")
        file = request.files["up_input"]
        user = User(address)
        C = Coingecko.init_from_cache(user)
        C.make_contracts_map()
        error, transactions_js = user.upload_csv(source, file, C, pb)
        C.dump(user)
        user.done()

        if error is None:
            js = {
                "success": 1,
                "transactions": transactions_js,
                "all_address_info": user.all_addresses,
            }
        else:
            js = {"error": error}
    except:
        log_error("EXCEPTION in upload_csv", address, request.args)
        js = {"error": "An error has occurred while uploading a file"}
    pb.set("Uploading to your browser", 100)
    redis.finish()
    data = json.dumps(js)
    return data


@uploads.route("/delete_upload", methods=["GET", "POST"])
def delete_upload():
    address = normalize_address(request.args.get("address"))
    persist(address)
    try:
        form = request.form

        upload_source = form["chain"]

        log("delete upload", address, upload_source)

        user = User(address)
        txids_to_delete = user.delete_upload(upload_source)
        user.load_addresses()
        user.load_tx_counts()
        user.done()
        js = {"success": 1, "txids": txids_to_delete, "all_address_info": user.all_addresses}
    except:
        log("EXCEPTION in delete_upload", traceback.format_exc())
        log_error("EXCEPTION in delete_upload", address, request.args, request.form)
        js = {"error": "An error has occurred while deleting an upload"}
    data = json.dumps(js)
    return data
