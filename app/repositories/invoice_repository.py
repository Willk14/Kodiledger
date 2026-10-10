from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.property import Property
from app.models.tenant import Tenant
from app.models.unit import Unit


class DuplicateInvoiceNumberError(Exception):
    """Raised when PostgreSQL rejects a duplicate invoice number."""


class InvoiceRepository:
    """Persistence operations for tenant invoices."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_by_landlord(self, landlord_id: str) -> list[Invoice]:
        result = await self.db.execute(
            select(Invoice)
            .where(Invoice.landlord_id == landlord_id)
            .order_by(
                Invoice.billing_month.asc(),
                Invoice.created_at.asc(),
                Invoice.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_by_id_and_landlord(
        self,
        *,
        invoice_id: str,
        landlord_id: str,
    ) -> Invoice | None:
        result = await self.db.execute(
            select(Invoice).where(
                Invoice.id == invoice_id,
                Invoice.landlord_id == landlord_id,
            )
        )
        return result.scalar_one_or_none()

    async def unit_belongs_to_landlord(
        self,
        *,
        unit_id: str,
        landlord_id: str,
    ) -> bool:
        result = await self.db.execute(
            select(Unit.id)
            .join(Property, Unit.property_id == Property.id)
            .where(
                Unit.id == unit_id,
                Unit.landlord_id == landlord_id,
                Property.landlord_id == landlord_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def tenant_belongs_to_unit_and_landlord(
        self,
        *,
        tenant_id: str,
        unit_id: str,
        landlord_id: str,
    ) -> bool:
        result = await self.db.execute(
            select(Tenant.id).where(
                Tenant.id == tenant_id,
                Tenant.unit_id == unit_id,
                Tenant.landlord_id == landlord_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self,
        *,
        landlord_id: str,
        values: dict[str, Any],
    ) -> Invoice:
        invoice = Invoice(landlord_id=landlord_id, **values)
        self.db.add(invoice)
        try:
            await self.db.flush()
            await self.db.refresh(invoice)
        except IntegrityError as exc:
            original: BaseException | None = exc.orig
            constraint_name = None
            while original is not None and constraint_name is None:
                constraint_name = getattr(original, "constraint_name", None)
                if constraint_name is None:
                    constraint_name = getattr(
                        getattr(original, "diag", None), "constraint_name", None
                    )
                original = original.__cause__
            if constraint_name == "invoices_invoice_number_key":
                raise DuplicateInvoiceNumberError from exc
            raise
        return invoice

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
                    COALESCE((
                        SELECT SUM(amount)
                        FROM payment_allocations
                        WHERE invoice_id = :invoice_id
                          AND status = 'ALLOCATED'
                    ), 0) + COALESCE((
                        SELECT SUM(amount)
                        FROM payment_credit_applications
                        WHERE invoice_id = :invoice_id
                    ), 0) AS allocated_amount
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

                    COALESCE((
                        SELECT SUM(pa.amount)
                        FROM payment_allocations pa
                        WHERE pa.invoice_id = i.id
                          AND pa.status = 'ALLOCATED'
                    ), 0) + COALESCE((
                        SELECT SUM(pca.amount)
                        FROM payment_credit_applications pca
                        WHERE pca.invoice_id = i.id
                    ), 0) AS allocated_amount

                FROM invoices i

                WHERE i.id = :invoice_id
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
