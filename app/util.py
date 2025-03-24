import datetime
import os
import pprint
import time
import traceback
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, List, NotRequired, Optional, TypedDict, Unpack

from flask import current_app

from .constants import LOG_DIRNAME, USER_DIRNAME

Q = [
    Decimal(10) ** 0,
    Decimal(10) ** -1,
    Decimal(10) ** -2,
    Decimal(10) ** -3,
    Decimal(10) ** -4,
    Decimal(10) ** -5,
    Decimal(10) ** -6,
    Decimal(10) ** -7,
    Decimal(10) ** -8,
    Decimal(10) ** -9,
    Decimal(10) ** -10,
    Decimal(10) ** -11,
    Decimal(10) ** -12,
]


def dec(num: float, places: int) -> Decimal:
    return Decimal(num).quantize(Q[places], rounding=ROUND_HALF_EVEN)


class LogParams(TypedDict):
    buffer: NotRequired[Optional[List[str]]]
    ignore_time: NotRequired[bool]
    prettify: NotRequired[bool]
    filename: NotRequired[str]
    print_only: NotRequired[bool]
    log_only: NotRequired[bool]


class Logger:
    def __init__(
        self,
        address: Optional[str] = None,
        chain: Optional[str] = None,
        write_frequency: int = 1,
        do_print: bool = True,
        do_write: bool = True,
    ):
        self.files: defaultdict = defaultdict(dict)
        self.write_frequency = write_frequency
        self.address = address
        self.chain = chain
        self.do_write = do_write
        self.do_print = do_print

        path = os.path.join(current_app.instance_path, LOG_DIRNAME)
        if not os.path.exists(path):
            os.makedirs(path)

    def log(self, *args: Any, **kwargs: Unpack[LogParams]) -> None:
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

    def buf_to_file(self, filename: str, glob: bool = False) -> None:
        buffer = self.files[filename]["buffer"]
        do_write = False

        path = os.path.join(current_app.instance_path, LOG_DIRNAME)
        if len(buffer) > 0:
            if self.address is not None and not glob:
                path = os.path.join(current_app.instance_path, USER_DIRNAME)
                path = os.path.join(path, self.address)
                if not os.path.exists(path):
                    path = os.path.join(current_app.instance_path, LOG_DIRNAME)
            if glob and self.address is not None:
                buffer.insert(0, self.address + " ")
            if self.do_write or glob:
                do_write = True
            if do_write:
                with open(os.path.join(path, filename), "a", encoding="utf-8") as myfile:
                    myfile.write("".join(buffer))
        self.files[filename]["buffer"] = []
        self.files[filename]["last_write"] = time.time()

    def lprint(self, p: str, same_line: bool = True) -> None:
        if not self.do_print:
            return
        try:
            if same_line:
                print(p, end=" ")
            else:
                print(p)
        except (TypeError, ValueError, AttributeError):
            pass


def log(*args: Any, **kwargs: Unpack[LogParams]) -> None:
    debug_level = current_app.config["DEBUG_LEVEL"]

    if debug_level > 0:
        logger = Logger(address="glob")
        if debug_level == 1:
            kwargs["log_only"] = True
        logger.log(*args, **kwargs)


def log_error(*args: Any, **kwargs: Unpack[LogParams]) -> None:
    logger = Logger(address="glob")
    try:
        trace = traceback.format_exc()
        if trace is not None:
            args = tuple(list(args) + [trace])
    except (TypeError, ValueError, AttributeError):
        pass
    kwargs["filename"] = "global_error_log.txt"
    logger.log(*args, **kwargs)


def decustom(val: Optional[str]) -> tuple[Optional[str], bool]:
    custom = False
    try:
        if val is not None and val[:7] == "custom:":
            val = val[7:]
            custom = True
        return val, custom
    except (TypeError, ValueError):
        return val, custom


def sql_in(lst: Any) -> str:
    if isinstance(lst, (int, float, bool)):
        return "(" + str(lst) + ")"

    if isinstance(lst, str):
        return "('" + lst + "')"

    if isinstance(lst, set):
        lst = list(lst)
    try:
        return "('" + "','".join(lst) + "')"
    except TypeError:
        strlst = []
        for e in lst:
            strlst.append(str(e))
        return "(" + ",".join(strlst) + ")"


def normalize_address(address: str) -> str:
    if is_ethereum(address):
        address = address.lower()
    return address


def is_ethereum(address: str) -> bool:
    if len(address) == 42 and address[0] == "0" and address[1] in ["x", "X"]:
        return True
    return False


def is_solana(address: str) -> bool:
    if len(address) >= 32 and len(address) <= 44 and address.isalnum():
        return True
    return False


def timestamp_to_date(
    ts: float, and_time: bool = False, date_format: Optional[str] = None, utc: bool = False
) -> str:
    if date_format is None:
        if and_time:
            date_format = "%m/%d/%y %H:%M:%S"
        else:
            date_format = "%m/%d/%y"
    if utc:
        return datetime.datetime.utcfromtimestamp(ts).strftime(date_format)
    return datetime.datetime.fromtimestamp(ts).strftime(date_format)
