from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class StkPushRequestRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record_initiation(
        self, merchant_request_id: str, checkout_request_id: str
    ) -> None:
        await self.db.execute(
            text("""
                INSERT INTO stk_push_requests (
                    merchant_request_id, checkout_request_id,
                    request_status, callback_received_at
                ) VALUES (
                    :merchant_id, CAST(:checkout_id AS VARCHAR(100)),
                    CASE WHEN EXISTS (
                        SELECT 1 FROM raw_payment_webhooks
                        WHERE checkout_request_id = CAST(:checkout_id AS VARCHAR(100))
                    ) THEN 'CALLBACK_RECEIVED' ELSE 'PENDING' END,
                    (SELECT min(created_at) FROM raw_payment_webhooks
                     WHERE checkout_request_id = CAST(:checkout_id AS VARCHAR(100)))
                )
                ON CONFLICT (checkout_request_id) DO NOTHING
            """),
            {"merchant_id": merchant_request_id, "checkout_id": checkout_request_id},
        )

    async def get_by_checkout_id(self, checkout_request_id: str) -> dict[str, Any] | None:
        result = await self.db.execute(
            text("""
                SELECT id, merchant_request_id, checkout_request_id,
                       request_status, query_count, callback_received_at
                FROM stk_push_requests
                WHERE checkout_request_id = :checkout_id
            """),
            {"checkout_id": checkout_request_id},
        )
        row = result.mappings().one_or_none()
        return dict(row) if row else None

    async def list_unresolved(
        self, *, limit: int, offset: int
    ) -> tuple[list[dict[str, Any]], int]:
        count_result = await self.db.execute(
            text("""
                SELECT count(*)
                FROM stk_push_requests
                WHERE request_status IN ('PENDING', 'QUERY_ACCEPTED', 'SUCCEEDED')
                  AND callback_received_at IS NULL
            """)
        )
        total = int(count_result.scalar_one())
        rows_result = await self.db.execute(
            text("""
                SELECT id, checkout_request_id, request_status, query_count,
                       created_at, last_queried_at
                FROM stk_push_requests
                WHERE request_status IN ('PENDING', 'QUERY_ACCEPTED', 'SUCCEEDED')
                  AND callback_received_at IS NULL
                ORDER BY created_at ASC, id ASC
                LIMIT :limit OFFSET :offset
            """),
            {"limit": limit, "offset": offset},
        )
        return [dict(row) for row in rows_result.mappings().all()], total

    async def record_query(
        self, checkout_request_id: str, response: dict[str, Any]
    ) -> str:
        result_code = response.get("ResultCode")
        if result_code is not None:
            state = "SUCCEEDED" if str(result_code) == "0" else "FAILED"
        else:
            state = "QUERY_ACCEPTED" if str(response.get("ResponseCode")) == "0" else "PENDING"

        result = await self.db.execute(
            text("""
                UPDATE stk_push_requests
                SET request_status = CASE
                        WHEN callback_received_at IS NOT NULL THEN 'CALLBACK_RECEIVED'
                        ELSE :state END,
                    last_query_response = CAST(:response AS JSONB),
                    query_count = query_count + 1,
                    last_queried_at = now()
                WHERE checkout_request_id = :checkout_id
                RETURNING request_status
            """),
            {
                "checkout_id": checkout_request_id,
                "state": state,
                "response": json.dumps(response),
            },
        )
        return str(result.scalar_one())

    async def record_query_error(self, checkout_request_id: str) -> None:
        await self.db.execute(
            text("""
                UPDATE stk_push_requests
                SET last_query_response = CAST(:response AS JSONB),
                    query_count = query_count + 1,
                    last_queried_at = now(),
                    request_status = CASE
                        WHEN callback_received_at IS NOT NULL THEN 'CALLBACK_RECEIVED'
                        ELSE 'PENDING' END
                WHERE checkout_request_id = :checkout_id
            """),
            {
                "checkout_id": checkout_request_id,
                "response": json.dumps({"error": "Daraja status query failed"}),
            },
        )

    async def mark_callback_received(
        self, merchant_request_id: str, checkout_request_id: str
    ) -> bool:
        result = await self.db.execute(
            text("""
                UPDATE stk_push_requests
                SET request_status = 'CALLBACK_RECEIVED',
                    callback_received_at = COALESCE(callback_received_at, now())
                WHERE checkout_request_id = :checkout_id
                  AND merchant_request_id = :merchant_id
            """),
            {"checkout_id": checkout_request_id, "merchant_id": merchant_request_id},
        )
        # The update both verifies the exact provider-issued identifier pair
        # and records callback receipt atomically. A repeated callback still
        # matches and remains idempotently accepted.
        return bool(result.rowcount)
