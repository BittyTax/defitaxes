import datetime
import os
import pprint
import re
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


def prettyp(data: Any) -> str:
    return pprint.pformat(data, width=160)


def convert_ansi_to_html(text):
    """Convert ANSI color codes to HTML span tags with inline styles."""
    # ANSI foreground color mappings (standard terminal colors)
    ansi_fg_colors = {
        "30": "#000000",  # black
        "31": "#ff0000",  # red
        "32": "#00ff00",  # green
        "33": "#ffff00",  # yellow
        "34": "#0000ff",  # blue
        "35": "#ff00ff",  # magenta
        "36": "#00ffff",  # cyan
        "37": "#ffffff",  # white
        "90": "#808080",  # bright black (gray)
        "91": "#ff5555",  # bright red
        "92": "#55ff55",  # bright green
        "93": "#ffff55",  # bright yellow
        "94": "#5555ff",  # bright blue
        "95": "#ff55ff",  # bright magenta
        "96": "#55ffff",  # bright cyan
        "97": "#ffffff",  # bright white
    }

    # ANSI background color mappings (standard terminal colors)
    ansi_bg_colors = {
        "40": "#000000",  # black
        "41": "#ff0000",  # red
        "42": "#00ff00",  # green
        "43": "#ffff00",  # yellow
        "44": "#0000ff",  # blue
        "45": "#ff00ff",  # magenta
        "46": "#00ffff",  # cyan
        "47": "#ffffff",  # white
        "100": "#808080",  # bright black (gray)
        "101": "#ff5555",  # bright red
        "102": "#55ff55",  # bright green
        "103": "#ffff55",  # bright yellow
        "104": "#5555ff",  # bright blue
        "105": "#ff55ff",  # bright magenta
        "106": "#55ffff",  # bright cyan
        "107": "#ffffff",  # bright white
    }

    # Match ANSI escape sequences (including \033 format)
    ansi_pattern = re.compile(r"(?:\x1B|\033)\[([0-9;]+)m")

    result = []
    last_end = 0
    current_fg = None
    current_bg = None
    span_open = False

    for match in ansi_pattern.finditer(text):
        # Add text before this match
        result.append(text[last_end : match.start()])

        codes = match.group(1).split(";")

        # Process codes
        for code in codes:
            if code == "0":
                # Full reset
                current_fg = None
                current_bg = None
            elif code == "39":
                # Reset foreground only
                current_fg = None
            elif code == "49":
                # Reset background only
                current_bg = None
            elif code in ansi_fg_colors:
                current_fg = ansi_fg_colors[code]
            elif code in ansi_bg_colors:
                current_bg = ansi_bg_colors[code]

        # Close previous span if open
        if span_open:
            result.append("</span>")
            span_open = False

        # Build new span with current colors
        styles = []
        if current_fg:
            styles.append(f"color: {current_fg}")
        if current_bg:
            styles.append(f"background-color: {current_bg}")

        # Open new span if we have any styles
        if styles:
            result.append(f'<span style="{"; ".join(styles)}">')
            span_open = True

        last_end = match.end()

    # Add remaining text
    result.append(text[last_end:])

    # Close any remaining open span
    if span_open:
        result.append("</span>")

    return "".join(result)
