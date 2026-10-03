"""Cart state — DynamoDB primary, SQLite fallback.

Table: marketpulse-carts (PK: session_id). Falls back to a local SQLite
table when DynamoDB is unreachable or permissions are missing, so the
skill works everywhere and lights up DynamoDB when the IAM policy allows it.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from pathlib import Path

log = logging.getLogger("marketpulse.cart")

TABLE = os.environ.get("DYNAMODB_CART_TABLE", "marketpulse-carts")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_SQLITE = Path(__file__).resolve().parent.parent.parent / "data" / "carts.db"

_dynamo = None
_dynamo_ok: bool | None = None


def _dynamo_table():
    global _dynamo, _dynamo_ok
    if _dynamo_ok is not None:
        return _dynamo if _dynamo_ok else None
    try:
        import boto3
        from botocore.exceptions import ClientError
        res = boto3.resource("dynamodb", region_name=REGION)
        table = res.Table(TABLE)
        try:
            table.load()
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                table = res.create_table(
                    TableName=TABLE,
                    KeySchema=[{"AttributeName": "session_id", "KeyType": "HASH"}],
                    AttributeDefinitions=[{"AttributeName": "session_id", "AttributeType": "S"}],
                    BillingMode="PAY_PER_REQUEST",
                )
                table.wait_until_exists()
            else:
                raise
        _dynamo, _dynamo_ok = table, True
        log.info("DynamoDB cart backend active: %s", TABLE)
    except Exception as e:  # noqa: BLE001
        log.warning("DynamoDB unavailable (%s); using SQLite fallback", str(e)[:120])
        _dynamo_ok = False
    return _dynamo if _dynamo_ok else None


def _sqlite():
    _SQLITE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(_SQLITE)
    con.execute("CREATE TABLE IF NOT EXISTS carts "
                "(session_id TEXT PRIMARY KEY, items TEXT, updated INTEGER)")
    return con


def backend() -> str:
    return "dynamodb" if _dynamo_table() is not None else "sqlite"


def get_cart(session_id: str) -> dict:
    table = _dynamo_table()
    if table is not None:
        resp = table.get_item(Key={"session_id": session_id})
        item = resp.get("Item")
        return {"items": json.loads(item["items"]) if item else [], "backend": "dynamodb"}
    with _sqlite() as con:
        row = con.execute("SELECT items FROM carts WHERE session_id=?",
                          (session_id,)).fetchone()
        return {"items": json.loads(row[0]) if row else [], "backend": "sqlite"}


def save_cart(session_id: str, items: list) -> str:
    table = _dynamo_table()
    payload = json.dumps(items)
    if table is not None:
        table.put_item(Item={"session_id": session_id, "items": payload,
                             "updated": int(time.time())})
        return "dynamodb"
    with _sqlite() as con:
        con.execute("INSERT OR REPLACE INTO carts VALUES (?,?,?)",
                    (session_id, payload, int(time.time())))
        con.commit()
        return "sqlite"


def clear_cart(session_id: str) -> None:
    save_cart(session_id, [])
