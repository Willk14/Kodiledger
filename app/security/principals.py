from __future__ import annotations

from dataclasses import dataclass

from app.security.roles import Role


@dataclass(frozen=True)
class AuthenticatedContext:
    """
    Canonical authenticated identity and supported tenant scope.

    `tenant_id` is populated only for tenant-role memberships. There is no
    caretaker account entity in the current schema; a caretaker is represented
    by a user ID and assigned landlord scope in trusted membership data.
    """

    user_id: str
    role: Role
    landlord_id: str | None = None
    tenant_id: str | None = None


# Preserve the established name used by authorization dependencies.
Principal = AuthenticatedContext
