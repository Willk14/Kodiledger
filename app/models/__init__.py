"""Central SQLAlchemy model registry.

Import every mapped model here so string-based relationships can resolve even
when a caller imports only one model module.
"""

from app.models.app_user import AppUser
from app.models.invoice import Invoice
from app.models.landlord import Landlord
from app.models.ledger_entry import LedgerEntry
from app.models.outbox_event import OutboxEvent
from app.models.payment_allocation import PaymentAllocation
from app.models.payment_credit import PaymentCredit
from app.models.payment_credit_application import PaymentCreditApplication
from app.models.payment_processing import PaymentProcessing
from app.models.payment_transaction import PaymentTransaction
from app.models.property import Property
from app.models.raw_payment_webhook import RawPaymentWebhook
from app.models.tenant import Tenant
from app.models.unassigned_payment import UnassignedPayment
from app.models.unit import Unit
from app.models.user_device_token import UserDeviceToken
from app.models.user_membership import UserMembership
from app.models.utility_reading import UtilityReading

__all__ = [
    "AppUser",
    "Invoice",
    "Landlord",
    "LedgerEntry",
    "OutboxEvent",
    "PaymentAllocation",
    "PaymentCredit",
    "PaymentCreditApplication",
    "PaymentProcessing",
    "PaymentTransaction",
    "Property",
    "RawPaymentWebhook",
    "Tenant",
    "UnassignedPayment",
    "Unit",
    "UserDeviceToken",
    "UserMembership",
    "UtilityReading",
]
