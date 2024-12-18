# -*- coding: utf-8 -*-
import datetime
import decimal
import os
import pprint
import time
import traceback
from collections import defaultdict

from flask import current_app, g

Q = [
    decimal.Decimal(10) ** 0,
    decimal.Decimal(10) ** -1,
    decimal.Decimal(10) ** -2,
    decimal.Decimal(10) ** -3,
    decimal.Decimal(10) ** -4,
    decimal.Decimal(10) ** -5,
    decimal.Decimal(10) ** -6,
    decimal.Decimal(10) ** -7,
    decimal.Decimal(10) ** -8,
    decimal.Decimal(10) ** -9,
    decimal.Decimal(10) ** -10,
    decimal.Decimal(10) ** -11,
    decimal.Decimal(10) ** -12,
]


def dec(num, places=None):
    if places is None:
        return decimal.Decimal(num)
    return decimal.Decimal(num).quantize(Q[places], rounding=decimal.ROUND_HALF_EVEN)


# logger = None
class Logger:
    def __init__(self, address=None, chain=None, write_frequency=1, do_print=True, do_write=True):
        self.files = defaultdict(dict)
        self.write_frequency = write_frequency
        self.address = address
        self.chain = chain
        self.do_write = do_write
        self.do_print = do_print

    def log(self, *args, **kwargs):
        t = time.time()
        glob = False
        if "WRITE ALL" in args:
            for filename in self.files:
                self.buf_to_file(filename)
            return

        if "buffer" in kwargs and kwargs["buffer"] is not None:
            buffer = kwargs["buffer"]
            strings = []
            if "ignore_time" not in kwargs:
                tm = str(datetime.datetime.now())
                strings.append(tm)

            for s in args:
                if "prettify" in kwargs:
                    s = pprint.pformat(s)
                strings.append(str(s))
            buffer.append(" ".join(strings))
        else:
            if "filename" in kwargs:
                filename = kwargs["filename"]
                glob = True
            else:
                filename = "log.txt"
            if filename not in self.files:
                self.files[filename]["last_write"] = t
                self.files[filename]["buffer"] = []

            buffer = self.files[filename]["buffer"]
            if "ignore_time" not in kwargs:
                tm = str(datetime.datetime.now())
                if "print_only" not in kwargs:
                    buffer.append(tm + " ")
                if "log_only" not in kwargs:
                    self.lprint(tm)

            for s in args:
                if "prettify" in kwargs:
                    s = pprint.pformat(s)
                if "print_only" not in kwargs:
                    buffer.append(str(s) + " ")
                if "log_only" not in kwargs:
                    self.lprint(s)

            if "print_only" not in kwargs:
                buffer.append("\n")
            if "log_only" not in kwargs:
                self.lprint("", same_line=False)

            self.buf_to_file(filename, glob=glob)

    def buf_to_file(self, filename, glob=False):
        buffer = self.files[filename]["buffer"]
        do_write = False

        path = current_app.config["LOGS_DIR"]
        if len(buffer) > 0:
            if self.address is not None and not glob:
                path = os.path.join(current_app.config["USERS_DIR"], self.address)
                if not os.path.exists(path):
                    path = current_app.config["LOGS_DIR"]
            if glob and self.address is not None:
                buffer.insert(0, self.address + " ")
            if self.do_write or glob:
                do_write = True
            if do_write:
                with open(os.path.join(path, filename), "a", encoding="utf-8") as myfile:
                    myfile.write("".join(buffer))
        self.files[filename]["buffer"] = []
        self.files[filename]["last_write"] = time.time()

    def lprint(self, p, same_line=True):
        if not self.do_print:
            return
        try:
            if same_line:
                print(p, end=" ")
            else:
                print(p)
        except Exception:
            pass


def log(*args, **kwargs):
    debug_level = int(os.environ.get("debug"))

    if debug_level > 0:
        logger = Logger(address="glob")
        if debug_level == 1:
            kwargs["log_only"] = True
        logger.log(*args, **kwargs)


def log_error(*args, **kwargs):
    logger = Logger(address="glob")
    try:
        trace = traceback.format_exc()
        if trace is not None:
            args = list(args)
            args.append(trace)
    except:
        pass
    kwargs["filename"] = "global_error_log.txt"
    logger.log(*args, **kwargs)


def clog(transaction, *args, **kwargs):
    if transaction.hash == transaction.chain.hif:
        args = [transaction.hash] + list(args)
        log(*args, **kwargs)


class ProgressBar:
    def __init__(self, redis, max_pb=None):
        self.redis = redis
        self.max_pb = max_pb
        if max_pb is not None:
            self.redis.set("max_pb", max_pb)

    def update(self, entry=None, percent_add=None):
        if entry is not None:
            self.redis.set("progress_entry", entry)
        if percent_add is not None:
            current = self.redis.get("progress")
            if current is None:
                current = 0
            else:
                current = float(current)
            self.redis.set("progress", current + percent_add)
        self.redis.set("last_update", int(time.time()))

    def set(self, entry=None, percent=None):
        if entry is not None:
            self.redis.set("progress_entry", entry)
        if percent is not None:
            self.redis.set("progress", percent)
        self.redis.set("last_update", int(time.time()))

    def retrieve(self):
        return self.redis.get("progress_entry"), self.redis.get("progress")


def decustom(val):
    custom = False
    try:
        if val is not None and val[:7] == "custom:":
            val = val[7:]
            custom = True
        return val, custom
    except:
        return val, custom


def persist(address, chain_name=None):
    g.address = address
    g.chain_name = chain_name


def sql_in(lst):
    if isinstance(lst, (int, float, bool)):
        return "(" + str(lst) + ")"

    if isinstance(lst, str):
        return "('" + lst + "')"

    if isinstance(lst, set):
        lst = list(lst)
    try:
        return "('" + "','".join(lst) + "')"
    except:
        strlst = []
        for e in lst:
            strlst.append(str(e))
        return "(" + ",".join(strlst) + ")"


def normalize_address(address):
    if is_ethereum(address):
        address = address.lower()
    return address


def is_ethereum(address):
    if len(address) == 42 and address[0] == "0" and address[1] in ["x", "X"]:
        return True
    return False


def is_solana(address):
    if len(address) >= 32 and len(address) <= 44 and address.isalnum():
        return True
    return False


def timestamp_to_date(ts, and_time=False, format=None, utc=False):
    if format is None:
        if and_time:
            format = "%m/%d/%y %H:%M:%S"
        else:
            format = "%m/%d/%y"
    if utc:
        return datetime.datetime.utcfromtimestamp(ts).strftime(format)
    return datetime.datetime.fromtimestamp(ts).strftime(format)
