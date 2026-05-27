"""Persistence helpers for user feedback on AI responses.

Table: api_audit.ai_response_feedback
DDL: sql/gold/12_feedback.sql
"""

from __future__ import annotations

from app.db.connection import execute_query

_VALID_RATINGS = frozenset({"positive", "negative"})


async def insert_feedback(
    *,
    tenant_id: int,
    user_id: int,
    request_id: str,
    rating: str,
    comment: str | None,
) -> None:
    """Insert one feedback row.  Caller is responsible for validating *rating*."""
    await execute_query(
        """
        INSERT INTO api_audit.ai_response_feedback
            (request_id, tenant_id, user_id, rating, comment)
        VALUES (?, ?, ?, ?, ?);
        """,
        (request_id, tenant_id, user_id, rating, comment),
    )
