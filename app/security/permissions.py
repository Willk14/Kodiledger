from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    """
    Fine-grained application permissions.

    Permissions describe WHAT an actor can do.
    Roles determine WHICH actors receive those permissions.
    """

    # ========================================================
    # Property Management
    # ========================================================

    PROPERTY_READ = "property:read"
    PROPERTY_WRITE = "property:write"

    # ========================================================
    # Unit Management
    # ========================================================

    UNIT_READ = "unit:read"
    UNIT_WRITE = "unit:write"

    # ========================================================
    # Tenant Management
    # ========================================================

    TENANT_READ = "tenant:read"
    TENANT_WRITE = "tenant:write"

    # ========================================================
    # Invoice Management
    # ========================================================

    INVOICE_READ = "invoice:read"
    INVOICE_WRITE = "invoice:write"

    # ========================================================
    # Payment Management
    # ========================================================

    PAYMENT_READ = "payment:read"
    PAYMENT_CREATE = "payment:create"
    PAYMENT_REVERSE = "payment:reverse"
    PAYMENT_ASSIGN = "payment:assign"

    # ========================================================
    # Offline Payment Management
    # ========================================================
    #
    # Used specifically for manually recording payments
    # received outside the M-Pesa webhook flow, such as:
    # cash, bank transfer, PesaLink, or cheque.
    #
    # This is intentionally separate from PAYMENT_CREATE so
    # restricted actors such as CARETAKER do not receive broad
    # payment-creation authority.
    #

    OFFLINE_PAYMENT_CREATE = "payment:offline_create"

    # ========================================================
    # Utility Management
    # ========================================================

    UTILITY_READ = "utility:read"
    UTILITY_WRITE = "utility:write"

    # ========================================================
    # Meter Readings
    # ========================================================

    METER_READING_READ = "meter_reading:read"
    METER_READING_WRITE = "meter_reading:write"

    # ========================================================
    # Reports
    # ========================================================

    REPORT_READ = "report:read"
    REPORT_EXPORT = "report:export"

    # ========================================================
    # Reminder / Communication Configuration
    # ========================================================

    REMINDER_READ = "reminder:read"
    REMINDER_WRITE = "reminder:write"

    # ========================================================
    # Caretaker / Agent Management
    # ========================================================

    CARETAKER_READ = "caretaker:read"
    CARETAKER_WRITE = "caretaker:write"
    CARETAKER_REVOKE = "caretaker:revoke"

    # ========================================================
    # Audit
    # ========================================================

    AUDIT_READ = "audit:read"

    