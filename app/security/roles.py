from enum import StrEnum


class Role(StrEnum):
    """
    Application roles.

    LANDLORD:
        Full administrative control over the landlord's portfolio.

    CARETAKER:
        Restricted operational access.

    TENANT:
        Limited tenant-facing access.

    ADMIN:
        Platform administration and operations.

    SYSTEM:
        Trusted internal service-to-service operations.
    """

    LANDLORD = "LANDLORD"
    CARETAKER = "CARETAKER"
    TENANT = "TENANT"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"