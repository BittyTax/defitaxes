import json
import os
import traceback

from flask import Blueprint, current_app, request

from ..constants import USER_DIRNAME
from ..sqlite import SQLite
from ..user import User
from ..util import log, log_error, normalize_address

admin = Blueprint("admin", __name__)


@admin.route("/wipe", methods=["GET"])
def wipe():
    address = normalize_address(request.args.get("address"))
    try:
        user = User(address)
        user.wipe_transactions()
        user.done()
        js = {"success": 1}
    except:
        log("EXCEPTION in wipe", traceback.format_exc())
        log_error("EXCEPTION in wipe", address, request.args)
        js = {"error": "An error has occurred while wiping transactions"}
    data = json.dumps(js)
    return data


@admin.route("/restore", methods=["GET"])
def restore():
    address = normalize_address(request.args.get("address"))
    try:
        user = User(address)
        user.restore_backup()
        user.done()
        js = {"success": 1}
    except:
        log("EXCEPTION in restore", traceback.format_exc())
        log_error("EXCEPTION in restore", address, request.args)
        js = {"error": "An error has occurred while restoring from backup"}
    data = json.dumps(js)
    return data


@admin.route("/cross_user", methods=["GET"])
def cross_user():
    dirs = os.listdir(os.path.join(current_app.instance_path, USER_DIRNAME))
    query = "SELECT count(id) FROM custom_types_rules WHERE token=='base'"
    count = 0

    non_fail_count = 0
    dump = ""
    for address in dirs:
        if len(address) == 42:
            try:
                user_db = SQLite(f"users/{address}/db", read_only=True)
                res = user_db.select(query)
                stat = res[0][0]
                user_db.disconnect()
                if stat > 0:
                    count += 1
                non_fail_count += 1
            except:
                dump += " " + traceback.format_exc()
    return str(count) + " " + str(non_fail_count) + " " + dump
