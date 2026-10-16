"""Stable pagination for authenticated metadata collections."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from fastapi import HTTPException, Query
from pydantic import BaseModel, Field


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class Pagination(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=25, ge=1, le=100)
    q: str = Field(default="", max_length=200)


def pagination(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), q: str = Query("", max_length=200)) -> Pagination:
    return Pagination(page=page, page_size=page_size, q=q)


def contains(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def date_bounds(lower: datetime | None, upper: datetime | None) -> None:
    if any(value is not None and value.tzinfo is None for value in (lower, upper)) or (lower and upper and lower > upper):
        raise HTTPException(422, detail="INVALID_DATE_RANGE")


def fetch_page(conn: psycopg.Connection, *, projection: str, source: str, predicates: list[str], params: list[Any], order: str, paging: Pagination) -> dict:
    # SQL fragments are static caller-owned constants; all request values are bound.
    where = " AND ".join(predicates)
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {source} WHERE {where}", params)
        total = cur.fetchone()[0]
        cur.execute(f"SELECT {projection} FROM {source} WHERE {where} ORDER BY {order} LIMIT %s OFFSET %s", [*params, paging.page_size, (paging.page - 1) * paging.page_size])
        names = [column.name for column in cur.description]
        items = [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}
