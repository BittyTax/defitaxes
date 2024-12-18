# -*- coding: utf-8 -*-
import os
import sqlite3
import sys
import time
import traceback
import warnings
from collections import defaultdict
from queue import Queue
from sqlite3 import Error

from flask import current_app

from .util import log, log_error


class SQLite:
    def __init__(
        self,
        db=None,
        check_same_thread=True,
        isolation_level="DEFERRED",
        read_only=False,
        do_logging=False,
    ):
        warnings.filterwarnings("ignore", category=DeprecationWarning)

        self.deferred_buffers = defaultdict(Queue)
        self.currently_processing = False
        self.conn = None
        self.read_only = read_only
        self.do_logging = do_logging
        self.do_error_logging = True
        self.db = db

        if db is not None:
            self.connect(db, check_same_thread=check_same_thread, isolation_level=isolation_level)

    def execute_and_log(self, cursor, query, values=None):
        tstart = time.time()
        error = None
        try:
            if values is None:
                rv = cursor.execute(query)
            else:
                rv = cursor.execute(query, values)
        except:
            error = traceback.format_exc()
        tend = time.time()
        if error is not None and self.do_error_logging:
            log_error("SQL ERROR", self.db, query, "VALUES", values, "ERROR", error)

        if self.do_logging:
            log("SQL QUERY", self.db, query, "VALUES", values, "TIMING", str(tend - tstart))

            if error is not None and self.do_error_logging:
                log("SQL ERROR", self.db, error)

        if error:
            sys.exit(1)
        return rv

    def connect(self, db=None, check_same_thread=True, isolation_level="DEFERRED"):
        if db is not None:
            self.db = db

        db_uri = os.path.join(current_app.config["DATA_DIR"], f"{db}.db")

        if self.read_only:
            self.conn = sqlite3.connect(
                f"file:{db_uri}?mode=ro",
                timeout=5,
                check_same_thread=check_same_thread,
                isolation_level=isolation_level,
                uri=True,
            )
        else:
            self.conn = sqlite3.connect(
                db_uri,
                timeout=5,
                check_same_thread=check_same_thread,
                isolation_level=isolation_level,
            )

        self.conn.row_factory = sqlite3.Row

    def disconnect(self):
        if self.conn is not None:
            # print("DISCONNECT FROM " + self.db)
            self.conn.close()
            self.conn = None

    def commit(self):
        self.conn.commit()

    def create_table(self, table_name, fields, drop=True):
        conn = self.conn
        c = conn.cursor()
        if drop:
            query = "DROP TABLE IF EXISTS " + table_name
            self.execute_and_log(c, query)
        query = "CREATE TABLE IF NOT EXISTS " + table_name + " (" + fields + ")"
        self.execute_and_log(c, query)
        conn.commit()

    def create_index(self, index_name, table_name, fields, unique=False):
        conn = self.conn
        c = conn.cursor()
        query = "CREATE "
        if unique:
            query += "UNIQUE "
        query += "INDEX IF NOT EXISTS " + index_name + " on " + table_name + " (" + fields + ")"
        self.execute_and_log(c, query)
        conn.commit()

    def query(self, q, commit=True, value_list=None):
        c = self.conn.cursor()
        if value_list is None:
            self.execute_and_log(c, q)
        else:
            self.execute_and_log(c, q, value_list)
        modified = c.rowcount
        if commit:
            self.commit()
        return modified

    def infer_meaning(self, value, keyworded=False):
        if isinstance(value, str):
            if keyworded:
                return "'" + value + "'"
            return value
        if isinstance(value, bytes):
            return sqlite3.Binary(value)
        if value in [True, False]:
            return str(int(value))
        if value is None:
            if keyworded:
                return "null"
            return None
        return str(value)

    def insert_kw(self, table, **kwargs):
        placeholder_list = []

        column_list = []
        value_list = []
        command_list = {"commit": False, "connection": None, "ignore": False, "values": None}
        for key, value in kwargs.items():
            if key in command_list:
                command_list[key] = value
                continue
            column_list.append(key)
            value_list.append(self.infer_meaning(value))
            placeholder_list.append("?")

        error_mode = "REPLACE"
        if command_list["ignore"]:
            error_mode = "IGNORE"

        conn_to_use = self.conn
        if command_list["connection"] is not None:
            conn_to_use = command_list["connection"]

        if command_list["values"] is not None:
            value_list = []

            for value in command_list["values"]:
                value_list.append(self.infer_meaning(value))

                placeholder_list.append("?")
            query = (
                "INSERT OR "
                + error_mode
                + " INTO "
                + table
                + " VALUES ("
                + ",".join(placeholder_list)
                + ")"
            )
        else:
            query = (
                "INSERT OR "
                + error_mode
                + " INTO "
                + table
                + " ("
                + ",".join(column_list)
                + ") VALUES ("
                + ",".join(placeholder_list)
                + ")"
            )
        c = self.execute_and_log(conn_to_use, query, value_list)

        try:

            if command_list["commit"]:
                conn_to_use.commit()
            return c.rowcount
        except Error as e:
            print(self.db, "insert_kw error ", e, "table", table, "kwargs", kwargs)
            sys.exit(0)

    def deferred_insert(self, table, values):
        buffer = self.deferred_buffers[table]
        if values is not None:
            converted_values = []
            for value in values:
                if isinstance(value, bytes):
                    converted_values.append(sqlite3.Binary(value))
                else:
                    converted_values.append(str(value))
            buffer.put(converted_values)

    def process_deferred_inserts(
        self, min_count, max_count_total=100, _error_mode="IGNORE", single_table=False
    ):
        if self.currently_processing:
            print("CURRENTLY IN INSERTS!!!")
        self.currently_processing = True
        tables = list(self.deferred_buffers.keys())
        len_list = []
        for table in tables:
            len_list.append((table, self.deferred_buffers[table].qsize()))
        len_list.sort(key=lambda tup: -tup[1])

        total_cnt = 0
        table_cnt = 0
        exec_time = 0
        self.conn.execute("BEGIN TRANSACTION")
        for table, _ in len_list:
            if self.deferred_buffers[table].qsize() >= min_count:
                values = self.deferred_buffers[table].get()
                placeholder_list = ["?"] * len(values)
                query = (
                    "INSERT OR REPLACE INTO "
                    + table
                    + " VALUES ("
                    + ",".join(placeholder_list)
                    + ")"
                )
                query_list = []

                query_list.append(values)
                total_cnt += 1

                # current_length = len(buffer) #buffer may grow while processing it!
                # In that case this may never finish unless short-circuited.
                while not self.deferred_buffers[table].empty() and total_cnt < max_count_total:
                    values = self.deferred_buffers[table].get()
                    query_list.append(values)
                    total_cnt += 1

                table_cnt += 1
                t = time.time()
                try:
                    self.conn.executemany(query, query_list)
                except:
                    raise NotImplementedError(
                        "Couldn't handle query " + query + ", values" + str(query_list),
                        traceback.format_exc(),
                    )
                exec_time += time.time() - t
            if total_cnt >= max_count_total:
                break
            if single_table:
                break

        remaining_cnt = 0
        tables = list(self.deferred_buffers.keys())
        for table in tables:
            remaining_cnt += self.deferred_buffers[table].qsize()
        self.conn.execute("COMMIT")
        self.currently_processing = False
        return table_cnt, total_cnt, remaining_cnt, exec_time

    def update_kw(self, table, where, **kwargs):
        pair_placeholder_list = []
        value_list = []
        command_list = {"commit": False, "connection": None, "ignore": False}
        for key, value in kwargs.items():
            if key in command_list:
                command_list[key] = value
                continue

            pair_placeholder_list.append(key + " = ?")
            value_list.append(self.infer_meaning(value))

        error_mode = "REPLACE"
        if command_list["ignore"]:
            error_mode = "IGNORE"
        query = (
            "UPDATE OR " + error_mode + " " + table + " SET " + (",").join(pair_placeholder_list)
        )
        if where is not None:
            query += " WHERE " + where

        conn_to_use = self.conn
        if command_list["connection"] is not None:
            conn_to_use = command_list["connection"]

        try:
            c = conn_to_use.cursor()
            self.execute_and_log(c, query, value_list)
            if command_list["commit"]:
                conn_to_use.commit()
            return c.rowcount
        except Error as e:
            print(self.db, "update_kw error ", e, "table", table, "kwargs", kwargs)
            sys.exit(1)

    def select(self, query, return_dictionaries=False, id_col=None, raw=False):
        conn = self.conn
        try:
            c = conn.cursor()
            self.execute_and_log(c, query)
            res = c.fetchall()
            if id_col is None:
                conv_res = []
                if return_dictionaries:
                    for row in res:
                        conv_res.append(dict(row))
                else:
                    if raw:
                        conv_res = res
                    else:
                        for row in res:
                            conv_res.append(list(row))
            else:
                conv_res = {}
                if return_dictionaries:
                    for row in res:
                        conv_res[row[id_col]] = dict(row)
                else:
                    for row in res:
                        conv_res[row[id_col]] = list(row)

            return conv_res
        except Error as e:
            print(self.db, "Error ", e, query)
            sys.exit(0)

    def attach(self, other_db_file, other_db_name):
        c = self.conn.cursor()
        c.execute("ATTACH '" + other_db_file + "' AS " + other_db_name)
        self.conn.commit()
