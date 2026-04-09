import json
import os
import time
import traceback

import requests as http
from flask import Blueprint, current_app, render_template, request

from ..constants import USER_DIRNAME
from ..redis_wrap import Redis
from ..sqlite import SQLite
from ..user import User
from ..util import log, log_error, normalize_address

admin = Blueprint("admin", __name__)


@admin.route("/")
def admin_page():
    return render_template("admin.html")


@admin.route("/api_usage")
def api_usage_page():
    return render_template("api_usage.html")


@admin.route("/api_usage_status", methods=["GET"])
def api_usage_status():
    result = {}

    # CoinGecko
    try:
        if current_app.config.get("COINGECKO_PRO"):
            resp = http.get(
                "https://pro-api.coingecko.com/api/v3/key",
                headers={"x-cg-pro-api-key": current_app.config["COINGECKO_API_KEY"]},
                timeout=10,
            )
            result["coingecko"] = (
                resp.json() if resp.status_code == 200 else {"error": resp.status_code}
            )
        else:
            result["coingecko"] = {"error": "Not using Pro API"}
    except Exception as e:
        result["coingecko"] = {"error": str(e)}

    # DeBank
    try:
        if current_app.config.get("DEBANK_API_KEY"):
            resp = http.get(
                "https://pro-openapi.debank.com/v1/account/units",
                headers={"AccessKey": current_app.config["DEBANK_API_KEY"]},
                timeout=10,
            )
            result["debank"] = (
                resp.json() if resp.status_code == 200 else {"error": resp.status_code}
            )
        else:
            result["debank"] = {"error": "No API key configured"}
    except Exception as e:
        result["debank"] = {"error": str(e)}

    # Etherscan
    try:
        if current_app.config.get("ETHERSCAN_API_KEY"):
            resp = http.get(
                "https://api.etherscan.io/v2/api",
                params={
                    "apikey": current_app.config["ETHERSCAN_API_KEY"],
                    "module": "getapilimit",
                    "action": "getapilimit",
                },
                timeout=10,
            )
            result["etherscan"] = (
                resp.json() if resp.status_code == 200 else {"error": resp.status_code}
            )
        else:
            result["etherscan"] = {"error": "No API key configured"}
    except Exception as e:
        result["etherscan"] = {"error": str(e)}

    return json.dumps(result)


@admin.route("/queue_status", methods=["GET"])
def queue_status():
    try:
        R = current_app.extensions["redis"]
        prefix = current_app.config["REDIS_PREFIX"]

        queue = R.lrange(f"{prefix}:{Redis.KEY_QUEUE}", 0, -1)
        now = int(time.time())

        entries = []
        for i, address in enumerate(queue):
            running = R.get(f"{prefix}:{address}:{Redis.KEY_RUNNING}")
            progress = R.get(f"{prefix}:{address}:{Redis.KEY_PROGRESS}")
            progress_entry = R.get(f"{prefix}:{address}:{Redis.KEY_PROGRESS_ENTRY}")
            last_update = R.get(f"{prefix}:{address}:{Redis.KEY_LAST_UPDATE}")

            entries.append(
                {
                    "address": address,
                    "position": i + 1,
                    "running": bool(running),
                    "progress": float(progress) if progress else 0.0,
                    "progress_entry": progress_entry or "",
                    "last_update": int(last_update) if last_update else None,
                    "last_update_ago": now - int(last_update) if last_update else None,
                }
            )

        return json.dumps({"queue": entries, "server_time": now})
    except:
        log("EXCEPTION in queue_status", traceback.format_exc())
        return json.dumps({"error": "Failed to fetch queue status"}), 500


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


@admin.route("/reset", methods=["GET"])
def reset():
    address = normalize_address(request.args.get("address"))
    try:
        redis = Redis(address)
        redis.wipe()
        js = {"success": 1}
    except:
        log("EXCEPTION in reset", traceback.format_exc())
        log_error("EXCEPTION in reset", address, request.args)
        js = {"error": "An error has occurred while resetting address"}
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
