import os
import sqlite3
import sys
import time
import traceback
import warnings
from typing import Any, List, NotRequired, Optional, TypedDict, Union

from flask import current_app


class CommandList(TypedDict):
    commit: bool
    ignore: bool
    values: NotRequired[Optional[List[Any]]]


class SQLite:
    def __init__(
        self,
        db: str,
        read_only: bool = False,
        do_logging: bool = False,
    ):
        if not current_app.debug:
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="sqlite3")

        self.do_logging = do_logging
        self.do_error_logging = True
        self.db = db

        db_path = os.path.join(current_app.instance_path, f"{db}.db")
        if read_only:
            self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", timeout=5, uri=True)
        else:
            self.conn = sqlite3.connect(db_path, timeout=5)
        self.conn.row_factory = sqlite3.Row

    def _execute_and_log(
        self, cursor: sqlite3.Cursor, query: str, values: Optional[List] = None
    ) -> None:
        tstart = time.time()
        error = None
        try:
            if values is None:
                cursor.execute(query)
            else:
                cursor.execute(query, values)
        except sqlite3.Error:
            error = traceback.format_exc()
        tend = time.time()
        if error is not None and self.do_error_logging:
            current_app.logger.error(
                "SQL ERROR %s %s VALUES %s ERROR %s", self.db, query, values, error
            )

        if self.do_logging:
            current_app.logger.debug(
                "SQL QUERY %s %s VALUES %s TIMING %s", self.db, query, values, str(tend - tstart)
            )

        if error:
            sys.exit(1)

    def disconnect(self) -> None:
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()

    def create_table(self, table_name: str, fields: str, drop: bool = True) -> None:
        c = self.conn.cursor()
        if drop:
            query = f"DROP TABLE IF EXISTS {table_name}"
            self._execute_and_log(c, query)

        query = f"CREATE TABLE IF NOT EXISTS {table_name} ({fields})"
        self._execute_and_log(c, query)
        self.conn.commit()

    def create_index(
        self, index_name: str, table_name: str, fields: str, unique: bool = False
    ) -> None:
        c = self.conn.cursor()
        query = "CREATE "
        if unique:
            query += "UNIQUE "
        query += f"INDEX IF NOT EXISTS {index_name} ON {table_name} ({fields})"
        self._execute_and_log(c, query)
        self.conn.commit()

    def query(self, q: str, commit: bool = True, value_list: Optional[List[Any]] = None) -> int:
        c = self.conn.cursor()
        self._execute_and_log(c, q, value_list)
        if commit:
            self.commit()
        return c.rowcount

    def execute(self, query: str, value_list: Optional[List[Any]] = None) -> int:
        c = self.conn.cursor()
        if value_list is not None:
            c.execute(query, value_list)
        else:
            c.execute(query)
        return c.rowcount

    def execute_many(self, query: str, value_list: List[Any]) -> int:
        c = self.conn.cursor()
        c.executemany(query, value_list)
        return c.rowcount

    def infer_meaning(
        self, value: Any, keyworded: bool = False
    ) -> Union[str, sqlite3.Binary, None]:
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

    def insert_kw(self, table: str, **kwargs: Any) -> int:
        column_list = []
        value_list: List[Union[str, sqlite3.Binary, None]] = []
        placeholder_list = []
        command_list: CommandList = {
            "commit": False,
            "ignore": False,
            "values": None,
        }

        for key, value in kwargs.items():
            if key == "commit":
                command_list["commit"] = value
            elif key == "ignore":
                command_list["ignore"] = value
            elif key == "values":
                command_list["values"] = value
            else:
                column_list.append(key)
                value_list.append(self.infer_meaning(value))
                placeholder_list.append("?")

        error_mode = "REPLACE"
        if command_list["ignore"]:
            error_mode = "IGNORE"

        if command_list["values"] is not None:
            value_list = []
            for value in list(command_list["values"]):
                value_list.append(self.infer_meaning(value))
                placeholder_list.append("?")

            query = f"INSERT OR {error_mode} INTO {table} VALUES ({','.join(placeholder_list)})"
        else:
            query = (
                f"INSERT OR {error_mode} INTO {table} ({','.join(column_list)}) "
                f"VALUES ({','.join(placeholder_list)})"
            )

        try:
            c = self.conn.cursor()
            self._execute_and_log(c, query, value_list)
            if command_list["commit"]:
                self.conn.commit()
            return c.rowcount
        except sqlite3.Error as e:
            current_app.logger.error(
                "%s insert_kw error %s table %s kwargs %s", self.db, e, table, kwargs
            )
            sys.exit(1)

    def update_kw(
        self,
        table: str,
        where: Optional[str],
        **kwargs: Any,
    ) -> int:
        value_list = []
        pair_placeholder_list = []
        command_list: CommandList = {"commit": False, "ignore": False}

        for key, value in kwargs.items():
            if key == "commit":
                command_list["commit"] = value
            elif key == "ignore":
                command_list["ignore"] = value
            else:
                value_list.append(self.infer_meaning(value))
                pair_placeholder_list.append(f"{key} = ?")

        error_mode = "REPLACE"
        if command_list["ignore"]:
            error_mode = "IGNORE"

        query = f"UPDATE OR {error_mode} {table} SET {','.join(pair_placeholder_list)}"
        if where is not None:
            query += f" WHERE {where}"

        try:
            c = self.conn.cursor()
            self._execute_and_log(c, query, value_list)
            if command_list["commit"]:
                self.conn.commit()
            return c.rowcount
        except sqlite3.Error as e:
            current_app.logger.error(
                "%s update_kw error %s table %s kwargs %s", self.db, e, table, kwargs
            )
            sys.exit(1)

    def select(
        self,
        query: str,
        return_dictionaries: bool = False,
        id_col: Optional[str] = None,
        raw: bool = False,
    ) -> Any:
        conn = self.conn
        try:
            c = conn.cursor()
            self._execute_and_log(c, query)
            res = c.fetchall()
            if id_col is None:
                conv_res: Any = []
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
        except sqlite3.Error as e:
            current_app.logger.error("%s Error %s %s", self.db, e, query)
            sys.exit(1)
