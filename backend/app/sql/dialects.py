from typing import Literal

from app.database_targets.exceptions import TargetConnectionError

DatabaseDialect = Literal["sqlite", "postgresql"]


def get_sqlglot_dialect(database_type: str) -> str:
    if database_type == "sqlite":
        return "sqlite"
    if database_type == "postgresql":
        return "postgres"
    raise TargetConnectionError("The database dialect is unsupported.")
