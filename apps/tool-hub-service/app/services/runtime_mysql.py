from __future__ import annotations

from urllib.parse import unquote, urlparse

try:
    import pymysql
except ImportError:  # pragma: no cover - exercised in integration environments
    pymysql = None


def normalize_mysql_dsn(value: str) -> str:
    return value.replace("mysql://", "mysql+pymysql://", 1) if value.startswith("mysql://") else value


def build_connection_params(dsn: str) -> dict[str, object]:
    parsed = urlparse(normalize_mysql_dsn(dsn))
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError(f"unsupported mysql dsn scheme: {parsed.scheme}")
    database = parsed.path.lstrip("/")
    if not database:
        raise ValueError("mysql dsn is missing a database name")
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "autocommit": False,
        "charset": "utf8mb4",
        "connect_timeout": 1,
        "read_timeout": 1,
        "write_timeout": 1,
    }


def connect(dsn: str):
    if pymysql is None:
        raise RuntimeError("PyMySQL dependency is unavailable")
    params = dict(build_connection_params(dsn))
    cursor_module = getattr(pymysql, "cursors", None)
    dict_cursor = getattr(cursor_module, "DictCursor", None)
    if dict_cursor is not None:
        params["cursorclass"] = dict_cursor
    return pymysql.connect(**params)


def _sanitize_identifier(value: str) -> str:
    normalized = value.strip()
    if not normalized or any(not (character.isalnum() or character == "_") for character in normalized):
        raise ValueError(f"invalid mysql identifier: {value!r}")
    return normalized


def create_index_if_missing(
    cursor,
    *,
    table_name: str,
    index_name: str,
    columns: tuple[str, ...],
) -> None:
    sanitized_table = _sanitize_identifier(table_name)
    sanitized_index = _sanitize_identifier(index_name)
    sanitized_columns = ", ".join(f"`{_sanitize_identifier(column)}`" for column in columns)
    sql = f"CREATE INDEX `{sanitized_index}` ON `{sanitized_table}` ({sanitized_columns})"
    try:
        cursor.execute(sql)
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" in message or "duplicate key name" in message or "duplicate index name" in message:
            return
        raise
