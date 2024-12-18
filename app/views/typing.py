# -*- coding: utf-8 -*-
import json
import traceback

from flask import Blueprint, request

from ..user import User
from ..util import log, log_error, normalize_address, persist

typing = Blueprint("typing", __name__)


@typing.route("/save_type", methods=["GET", "POST"])
def save_type():
    address = normalize_address(request.args.get("address"))
    persist(address)
    try:
        form = request.form

        name = form["tc_name"]
        chain_specific = False
        if "tc_chain" in form:
            chain_specific = True
        description = form["tc_desc"]
        balanced = 0
        if "tc_balanced" in form:
            balanced = int(form["tc_balanced"] == "on")

        rules = []
        idx = 0
        while "from_addr" + str(idx) in form:
            sidx = str(idx)
            rule = [
                form["from_addr" + sidx],
                form["from_addr_custom" + sidx],
                form["to_addr" + sidx],
                form["to_addr_custom" + sidx],
                form["rule_tok" + sidx],
                form["rule_tok_custom" + sidx],
                form["rule_treatment" + sidx],
                form["vault_id" + sidx],
                form["vault_id_custom" + sidx],
            ]
            rules.append(rule)
            idx += 1

        type_id = None
        if "type_id" in form:
            type_id = form["type_id"]

        log("create_type", address, name, chain_specific, type_id, rules)

        # T = Typing()
        user = User(address)
        user.save_custom_type(name, description, balanced, rules, id=type_id)

        custom_types = user.load_custom_types()
        user.done()
        js = {"custom_types": custom_types}
    except:
        log("EXCEPTION in save_type", traceback.format_exc())
        log_error("EXCEPTION in save_type", address, request.args, request.form)
        js = {"error": "An error has occurred while saving a type"}
    data = json.dumps(js)
    return data


@typing.route("/delete_type", methods=["GET", "POST"])
def delete_type():
    address = normalize_address(request.args.get("address"))
    persist(address)
    try:
        form = request.form

        type_id = form["type_id"]

        log("delete_type", address, type_id)

        user = User(address)
        processed_transactions = user.unapply_custom_type(type_id)
        user.delete_custom_type(type_id)

        custom_types = user.load_custom_types()
        user.done()
        js = {"custom_types": custom_types, "transactions": processed_transactions}
    except:
        log("EXCEPTION in delete_type", traceback.format_exc())
        log_error("EXCEPTION in delete_type", address, request.args, request.form)
        js = {"error": "An error has occurred while deleting a type"}
    data = json.dumps(js)
    return data


@typing.route("/apply_type", methods=["GET", "POST"])
def apply_type():
    address = normalize_address(request.args.get("address"))
    persist(address)
    try:
        form = request.form

        type_id = form["type_id"]
        transactions = form["transactions"]

        log("apply_type", address, type_id, transactions)
        user = User(address)
        user.get_custom_rates()
        processed_transactions = user.apply_custom_type(type_id, transactions.split(","))
        user.done()
        js = {"success": 1, "transactions": processed_transactions}
    except:
        log("EXCEPTION in apply_type", traceback.format_exc())
        log_error("EXCEPTION in apply_type", address, request.args, request.form)
        js = {"error": "An error has occurred while applying a type"}
    data = json.dumps(js)
    return data


@typing.route("/unapply_type", methods=["GET", "POST"])
def unapply_type():
    address = normalize_address(request.args.get("address"))
    persist(address)
    try:
        form = request.form

        type_id = form["type_id"]
        transactions = form["transactions"]

        log("unapply_type", address, type_id, transactions)
        user = User(address)
        user.get_custom_rates()
        processed_transactions = user.unapply_custom_type(type_id, transactions.split(","))
        user.done()
        js = {"success": 1, "transactions": processed_transactions}
    except:
        log("EXCEPTION in unapply_type", traceback.format_exc())
        log_error("EXCEPTION in unapply_type", address, request.args, request.form)
        js = {"error": "An error has occurred while unapplying a type"}
    data = json.dumps(js)
    return data
