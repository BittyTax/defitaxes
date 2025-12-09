from typing import Any, Dict

from .sqlite import SQLite


class UserConfig:
    def __init__(self, username: str) -> None:
        self.username = username

    def get_all_settings(self) -> Dict[str, Any]:
        db = SQLite("db", read_only=True)
        rows = db.select(
            f"SELECT transfer_in_known, transfer_in_unknown, transfer_out_known, "
            f"transfer_out_unknown, currency FROM user_config WHERE username = '{self.username}'",
            return_dictionaries=True,
        )
        db.disconnect()

        if rows:
            return rows[0]
        return {}

    def save_settings(
        self,
        transfer_in_known: int,
        transfer_in_unknown: int,
        transfer_out_known: int,
        transfer_out_unknown: int,
        currency: str,
    ) -> None:
        db = SQLite("db")
        db.insert_kw(
            "user_config",
            username=self.username,
            transfer_in_known=transfer_in_known,
            transfer_in_unknown=transfer_in_unknown,
            transfer_out_known=transfer_out_known,
            transfer_out_unknown=transfer_out_unknown,
            currency=currency,
            commit=True,
        )
        db.disconnect()

    @staticmethod
    def create_table(drop: bool = False) -> None:
        db = SQLite("db")
        db.create_table(
            "user_config",
            """
                username TEXT PRIMARY KEY,
                transfer_in_known INTEGER DEFAULT 0,
                transfer_in_unknown INTEGER DEFAULT 0,
                transfer_out_known INTEGER DEFAULT 0,
                transfer_out_unknown INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'USD'
            """,
            drop=drop,
        )
        db.disconnect()
