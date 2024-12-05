# -*- coding: utf-8 -*-
import calendar
import csv
import datetime
import json
import sys
import traceback
from collections import defaultdict
from decimal import Decimal

from .sqlite import SQLite
from .util import dec, log


def process_web_json(rates, address, year, mark_to_market, js):
    converted_rows = []
    for transaction in js:
        id = transaction["hash"]
        ts = transaction["ts"]
        rows = transaction["rows"]
        for row in rows:
            treatment = row["treatment"]
            if treatment == "ignore":
                continue
            contract = row["what"]
            if contract is None:
                contract = row["symbol"]
            amt = float(row["amount"])

            rate = row["rate"]
            if rate is None or rate == "null":
                rate = 0
            else:
                rate = float(rate)

            rates.add_rate(contract, row["symbol"], ts, rate)
            if treatment == "burn":
                converted_row = [id, ts, contract, "", "burn", "", amt, rate]
            if treatment == "gift":
                converted_row = [id, ts, contract, "", "gift", "", amt, rate]
            if treatment in ("buy", "buy_custom"):
                converted_row = [id, ts, "USD", contract, "buy", amt, amt * rate, rate]
            if treatment in ("sell", "sell_custom"):
                converted_row = [id, ts, "USD", contract, "sell", amt, amt * rate, rate]
            converted_rows.append(converted_row)

    with open(
        "data/" + address + "_transactions.json", "w", newline="", encoding="utf-8"
    ) as js_file:
        js_file.write(json.dumps(js))

    with open(
        "data/" + address + "_transactions.csv", "w", newline="", encoding="utf-8"
    ) as log_file:
        writer = csv.writer(log_file)
        writer.writerow(
            ["ID", "Timestamp", "Quote", "Base", "Side", "Base amount", "Quote Amount", "USD rate"]
        )
        writer.writerows(converted_rows)

    rv = log_to_4797(
        rates,
        "data/" + address + "_transactions.csv",
        "data/" + address + "_tax_form.csv",
        year=year,
        mark_to_market=mark_to_market,
        dispose_at_end=False,
    )
    return rv


def log_to_4797(
    coingecko_rates,
    filename,
    out_file,
    year=2020,
    mark_to_market=True,
    dispose_at_end=False,
    ignore=None,
    checkpoints=(),
):

    with open(filename, encoding="utf-8") as f:
        csv_reader = csv.reader(f, delimiter=",")
        rows = []

        for idx, row in enumerate(csv_reader):
            rows.append(row)

    current = []
    total_gain = 0
    current = defaultdict(list)

    def adjust_holding(currency, ts, amt, price, stored_rv=None):
        if amt == 0:
            return stored_rv

        holdings = current[currency]
        basis = 0
        sale = 0
        stamps = []

        # increase long position
        if amt > 0 and (len(holdings) == 0 or holdings[0]["amount"] > 0):
            holdings.append({"ts": ts, "amount": amt, "open_price": price})
            return stored_rv
        # decrease long position
        if amt < 0 and (len(holdings) > 0 and holdings[0]["amount"] > 0):
            amt = -amt
            start_amt = amt
            while amt > 0:
                if len(holdings) == 0:
                    # print(ts, "Switching into short", amt, currency)
                    return adjust_holding(
                        currency,
                        ts,
                        -amt,
                        price,
                        stored_rv=(start_amt - amt, basis, sale, stamps, False),
                    )
                if holdings[0]["amount"] > amt:
                    holdings[0]["amount"] -= amt
                    open_price = holdings[0]["open_price"]
                    basis += amt * open_price
                    sale += amt * price
                    stamps.append(holdings[0]["ts"])
                    amt = 0
                else:
                    open_price = holdings[0]["open_price"]
                    basis += holdings[0]["amount"] * open_price
                    sale += holdings[0]["amount"] * price
                    amt -= holdings[0]["amount"]
                    stamps.append(holdings[0]["ts"])
                    del holdings[0]

            return start_amt, basis, sale, stamps, False

        # increase short position
        if amt < 0 and (len(holdings) == 0 or holdings[0]["amount"] < 0):
            # print("short+",amt,currency)
            holdings.append({"ts": ts, "amount": amt, "open_price": price})
            return stored_rv

        # decrease short position
        if amt > 0 and (len(holdings) > 0 and holdings[0]["amount"] < 0):
            # print("short-", amt,currency)
            start_amt = amt
            while amt > 0:
                if len(holdings) == 0:
                    # print(ts, "Switching into long", amt, currency)
                    return adjust_holding(
                        currency,
                        ts,
                        amt,
                        price,
                        stored_rv=(start_amt - amt, basis, sale, stamps, True),
                    )
                if -holdings[0]["amount"] > amt:
                    holdings[0]["amount"] += amt
                    open_price = holdings[0]["open_price"]
                    sale += amt * open_price
                    basis += amt * price
                    stamps.append(holdings[0]["ts"])
                    amt = 0
                else:
                    open_price = holdings[0]["open_price"]
                    sale += (-holdings[0]["amount"]) * open_price
                    basis += (-holdings[0]["amount"]) * price
                    amt += holdings[0]["amount"]
                    stamps.append(holdings[0]["ts"])
                    del holdings[0]
            return start_amt, basis, sale, stamps, True
        log("WTF", amt, holdings)
        sys.exit(1)

    total_fees_2 = 0

    def write_records(currency, ts, transaction, fee=None):
        nonlocal total_gain, total_fees_2, year

        dt = datetime.datetime.utcfromtimestamp(ts)
        if dt.year != year:
            return 0, None

        currency = coingecko_rates.lookup_name(currency)

        if transaction is not None:
            amt, basis, sale, stamps, short = transaction
            assert amt > 0

            days = set()
            for stamp in stamps:
                d = datetime.datetime.utcfromtimestamp(stamp).strftime("%m/%d/%Y")
                days.add(d)
            open_days = ",".join(list(days))
            close_day = datetime.datetime.utcfromtimestamp(ts).strftime("%m/%d/%Y")

            if not short:
                buy_ts = open_days
                sell_ts = close_day
            else:
                buy_ts = close_day
                sell_ts = open_days

            if fee is not None:
                _, fee_basis, fee_sale, _fee_stamps, _ = fee
                assert fee_sale == 0
                basis += fee_basis
                total_fees_2 += fee_basis
            gain = sale - basis
            total_gain += gain
            if abs(gain) < 0.01:
                gain = 0

            if sale != 0:
                sale = dec(sale, 8)
            else:
                sale = "0"

            if basis != 0:
                basis = dec(basis, 8)
            else:
                basis = "0"

            if gain != 0:
                gain = dec(gain, 8)
            else:
                gain = "0"

            form_entry = [str(dec(amt, 8)) + " " + currency, buy_ts, sell_ts, sale, basis, gain]

            return gain, form_entry
        return 0, None

    running_amounts = defaultdict(Decimal)
    total_fees = 0

    def format_holdings(holdings, ts):
        formatted_holdings = []
        if holdings is None:
            return {}
        for k in holdings:
            amt = 0
            if len(holdings[k]) > 0:

                for entry in holdings[k]:
                    amt += float(entry["amount"])

                if amt > 1e-8:
                    currency_name = coingecko_rates.lookup_name(k)
                    _, rate = coingecko_rates.lookup_rate(k, ts)
                    formatted_holdings.append((currency_name, amt, rate))
        log("formatted holdings", formatted_holdings)
        return formatted_holdings

    def period_edge_process(row_year):
        log("Add up at edge", row_year)
        dt = datetime.date(row_year, 1, 1)
        ts = calendar.timegm(dt.timetuple())
        log("edge", row_year, ts)
        log(current)
        amounts = {}
        for k in current:
            amt = 0
            if len(current[k]) > 0:

                for entry in current[k]:
                    amt += entry["amount"]

                if amt > 1e-8:
                    currency_name = coingecko_rates.lookup_name(k)
                    log(currency_name, amt)
                    row = ["withdrawal-end", str(ts - 1), k, "", "withdrawal", "", str(amt)]
                    proc_row(row, synthetic=True)
                    amounts[k] = amt

        for k in amounts:
            row = ["deposit-start", str(ts), k, "", "deposit", "", str(amounts[k])]
            proc_row(row, synthetic=True)

    fiat = ["USD"]
    form = []
    gain_per_form = 0
    op_counts = defaultdict(int)

    def proc_row(row, synthetic=False):
        nonlocal total_gain, total_fees_2, gain_per_form, op_counts
        ts = int(row[1])
        op = row[4].lower()
        base = row[3]  # .upper()
        quote = row[2]  # .upper()
        if ignore is not None and (base in ignore or quote in ignore):
            return
        base_amt = row[5]

        if base_amt != "":
            base_amt = dec(base_amt)
        if base_amt == 0:
            log("skipping", row)
            return
        quote_amt = dec(row[6])
        if base_amt != "":
            price = quote_amt / base_amt
        else:
            price = None
        fee_currency = None
        fee_amt = 0
        if fee_amt != "":
            fee_amt = dec(fee_amt)
        form_entry = None
        form_entry2 = None

        if not synthetic:
            op_counts[op] += 1

        if op == "gift":
            running_amounts[quote] += quote_amt
            if quote not in fiat:
                rv = adjust_holding(quote, ts, quote_amt, 0)
                _gain, form_entry = write_records(quote, ts, rv)
        elif op in ("deposit", "initial"):
            running_amounts[quote] += quote_amt
            if quote not in fiat:
                _, rate = coingecko_rates.lookup_rate(quote, ts)
                rv = adjust_holding(quote, ts, quote_amt, dec(rate))
                _gain, form_entry = write_records(quote, ts, rv)
        elif op == "buy":
            running_amounts[quote] -= quote_amt
            running_amounts[base] += base_amt
            if fee_currency is not None:
                running_amounts[fee_currency] -= fee_amt
                _, fee_rate = coingecko_rates.lookup_rate(fee_currency, ts)
                total_fees += fee_amt * dec(fee_rate)
                rv_fee = adjust_holding(fee_currency, ts, -fee_amt, 0)
            else:
                rv_fee = None

            _, quote_rate = coingecko_rates.lookup_rate(quote, ts)
            usd_price = price * dec(quote_rate)
            rv = adjust_holding(base, ts, base_amt, usd_price)

            _gain, form_entry = write_records(
                base, ts, rv, rv_fee
            )  # record is only written on transaction close. Only base OR quote will close.
            # So fee will only be written once.
            if quote != "USD":
                rv_quote = adjust_holding(quote, ts, -quote_amt, dec(quote_rate))
                _gain, form_entry2 = write_records(quote, ts, rv_quote, rv_fee)

        elif op == "burn":
            running_amounts[quote] -= quote_amt
            if quote not in fiat:
                _, quote_rate = coingecko_rates.lookup_rate(quote, ts)
                rv = adjust_holding(quote, ts, -quote_amt, 0)
                _gain, form_entry = write_records(quote, ts, rv)

        elif op == "withdrawal":
            running_amounts[quote] -= quote_amt
            if quote not in fiat:
                try:
                    _, quote_rate = coingecko_rates.lookup_rate(quote, ts)
                except:
                    log("problem", row, ts, quote, traceback.format_exc())
                    sys.exit(10)
                rv = adjust_holding(quote, ts, -quote_amt, dec(quote_rate))
                _gain, form_entry = write_records(quote, ts, rv)

        elif op == "sell":
            running_amounts[quote] += quote_amt
            running_amounts[base] -= base_amt
            if fee_currency is not None:
                running_amounts[fee_currency] -= fee_amt
                _, fee_rate = coingecko_rates.lookup_rate(fee_currency, ts)
                rv_fee = adjust_holding(fee_currency, ts, -fee_amt, 0)
                total_fees += fee_amt * fee_rate
            else:
                rv_fee = None

            _, quote_rate = coingecko_rates.lookup_rate(quote, ts)
            usd_price = price * dec(quote_rate)

            rv = adjust_holding(base, ts, -base_amt, usd_price)

            if quote not in fiat:
                rv_quote = adjust_holding(quote, ts, quote_amt, quote_rate)
                _gain, form_entry2 = write_records(quote, ts, rv_quote, rv_fee)

            _gain, form_entry = write_records(base, ts, rv, rv_fee)

        if form_entry is not None:
            gain_per_form += dec(form_entry[-1])
            form.append(form_entry)

        if form_entry2 is not None:
            gain_per_form += dec(form_entry2[-1])
            form.append(form_entry2)

    checkpoint_idx = 0
    total_gpf_so_far = 0
    current_year = 0
    start_holdings = []
    end_holdings = None

    dt = datetime.date(year, 1, 1)
    start_ts = calendar.timegm(dt.timetuple())
    dt = datetime.date(year + 1, 1, 1)
    end_ts = calendar.timegm(dt.timetuple())

    for idx, row in enumerate(rows):
        ts = int(row[1])
        dt = datetime.datetime.utcfromtimestamp(ts)
        row_year = dt.year

        if row_year != current_year:
            if row_year == year:
                start_holdings = format_holdings(current, start_ts)
            if row_year == year + 1:
                end_holdings = format_holdings(current, end_ts)
            if mark_to_market:
                period_edge_process(row_year)
            current_year = row_year

        if checkpoint_idx < len(checkpoints):
            if ts > checkpoints[checkpoint_idx]:
                log("CHECKPOINT", checkpoints[checkpoint_idx], gain_per_form - total_gpf_so_far)
                total_gpf_so_far = gain_per_form
                checkpoint_idx += 1

        proc_row(row)

        if idx % 1000 == 0:
            log(idx, running_amounts)

    if end_holdings is None:
        end_holdings = format_holdings(current, end_ts)

    if dispose_at_end:
        period_edge_process(row_year + 1)

    log("Gain", total_gain, "tf", total_fees, total_fees_2)
    log("Gain as per form after last checkpoint", gain_per_form - total_gpf_so_far)
    log("Gain as per form total", gain_per_form)

    log(dict(op_counts))

    with open(out_file, "w", newline="", encoding="utf-8") as log_file:
        writer = csv.writer(log_file)
        writer.writerow(
            [
                "Currency",
                "Date Acquired",
                "Date Sold",
                "Gross Sales Price",
                "Cost Basis",
                "Gain or Loss",
            ]
        )
        writer.writerows(form)

    return total_gain, start_holdings, end_holdings, dict(op_counts)


def formalize_names(chain, user="0xd603a49886c9b500f96c0d798aed10068d73bf7c"):
    address_db = SQLite("addresses")
    address_db.query(
        "INSERT OR REPLACE INTO "
        + chain
        + "_names (address,name) SELECT address,name FROM "
        + chain
        + "_custom_names WHERE user='"
        + user
        + "'"
    )
    address_db.query("DELETE FROM " + chain + "_custom_names WHERE user='" + user + "'")
    address_db.disconnect()
