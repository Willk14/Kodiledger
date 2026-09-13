from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class InvoiceRepository:
    """Persistence operations for tenant invoices."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_oldest_unpaid_for_tenant_for_update(
        self,
        *,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        """
        Select the oldest unpaid invoice for a tenant and lock its row.

        IMPORTANT:
        This method ONLY selects and locks the invoice row.

        The allocated amount is deliberately calculated by a separate
        SQL statement after the lock has been acquired. This prevents
        the allocation decision from relying on a stale calculation
        from the original SELECT statement.
        """
        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    landlord_id,
                    unit_id,
                    tenant_id,
                    invoice_number,
                    billing_month,
                    rent_amount,
                    water_amount,
                    garbage_amount,
                    security_amount,
                    total_amount,
                    due_date,
                    is_paid,
                    created_at
                FROM invoices
                WHERE tenant_id = :tenant_id
                  AND is_paid = FALSE
                ORDER BY billing_month ASC, created_at ASC
                LIMIT 1
                FOR UPDATE
                """
            ),
            {
                "tenant_id": tenant_id,
            },
        )

        row = result.mappings().first()

        if not row:
            return None

        return dict(row)

    async def get_allocated_amount(
        self,
        *,
        invoice_id: str,
    ) -> Decimal:
        """
        Calculate the currently allocated amount for an invoice.

        This query is intentionally separate from the FOR UPDATE query.
        It runs after the invoice row has been locked.
        """
        result = await self.db.execute(
            text(
                """
                SELECT
                    COALESCE(
                        SUM(amount),
                        0
                    ) AS allocated_amount
                FROM payment_allocations
                WHERE invoice_id = :invoice_id
                  AND status = 'ALLOCATED'
                """
            ),
            {
                "invoice_id": invoice_id,
            },
        )

        row = result.mappings().first()

        if not row:
            return Decimal("0")

        return Decimal(str(row["allocated_amount"]))

    async def mark_paid(
        self,
        *,
        invoice_id: str,
    ) -> None:
        """
        Mark an invoice as fully paid.

        The caller is responsible for running this inside the current
        database transaction.
        """
        await self.db.execute(
            text(
                """
                UPDATE invoices
                SET is_paid = TRUE
                WHERE id = :invoice_id
                """
            ),
            {
                "invoice_id": invoice_id,
            },
        )

    async def get_by_id_for_update(
        self,
        *,
        invoice_id: str,
    ) -> dict[str, Any] | None:
        """
        Retrieve and lock a specific invoice row.
        """
        result = await self.db.execute(
            text(
                """
                SELECT
                    id,
                    landlord_id,
                    unit_id,
                    tenant_id,
                    invoice_number,
                    billing_month,
                    rent_amount,
                    water_amount,
                    garbage_amount,
                    security_amount,
                    total_amount,
                    due_date,
                    is_paid,
                    created_at
                FROM invoices
                WHERE id = :invoice_id
                FOR UPDATE
                """
            ),
            {
                "invoice_id": invoice_id,
            },
        )

        row = result.mappings().first()

        if not row:
            return None

        return dict(row)

    async def get_by_id(
        self,
        *,
        invoice_id: str,
    ) -> dict[str, Any] | None:
        """
        Retrieve an invoice and calculate its currently allocated amount.
        """
        result = await self.db.execute(
            text(
                """
                SELECT
                    i.id,
                    i.landlord_id,
                    i.unit_id,
                    i.tenant_id,
                    i.invoice_number,
                    i.billing_month,
                    i.rent_amount,
                    i.water_amount,
                    i.garbage_amount,
                    i.security_amount,
                    i.total_amount,
                    i.due_date,
                    i.is_paid,
                    i.created_at,

                    COALESCE(
                        SUM(
                            CASE
                                WHEN pa.status = 'ALLOCATED'
                                THEN pa.amount
                                ELSE 0
                            END
                        ),
                        0
                    ) AS allocated_amount

                FROM invoices i

                LEFT JOIN payment_allocations pa
                    ON pa.invoice_id = i.id

                WHERE i.id = :invoice_id

                GROUP BY
                    i.id,
                    i.landlord_id,
                    i.unit_id,
                    i.tenant_id,
                    i.invoice_number,
                    i.billing_month,
                    i.rent_amount,
                    i.water_amount,
                    i.garbage_amount,
                    i.security_amount,
                    i.due_date,
                    i.is_paid,
                    i.created_at

                LIMIT 1
                """
            ),
            {
                "invoice_id": invoice_id,
            },
        )

        row = result.mappings().first()

        if not row:
            return None

        return dict(row)

    