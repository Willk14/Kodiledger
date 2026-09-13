from __future__ import annotations

from collections.abc import Callable
from typing import TypeAlias

from fastapi import Depends, HTTPException, status

from app.security.dependencies import get_current_principal
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role


# ============================================================
# Types
# ============================================================

AuthorizationDependency: TypeAlias = Callable[..., Principal]


# ============================================================
# Role -> Permission Matrix
# ============================================================

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    # ========================================================
    # LANDLORD
    # ========================================================
    Role.LANDLORD: frozenset(
        {
            # Property
            Permission.PROPERTY_READ,
            Permission.PROPERTY_WRITE,
            # Units
            Permission.UNIT_READ,
            Permission.UNIT_WRITE,
            # Tenants
            Permission.TENANT_READ,
            Permission.TENANT_WRITE,
            # Invoices
            Permission.INVOICE_READ,
            Permission.INVOICE_WRITE,
            # Payments
            Permission.PAYMENT_READ,
            Permission.PAYMENT_CREATE,
            Permission.PAYMENT_REVERSE,
            Permission.PAYMENT_ASSIGN,
            Permission.OFFLINE_PAYMENT_CREATE,
            # Utilities
            Permission.UTILITY_READ,
            Permission.UTILITY_WRITE,
            # Meter readings
            Permission.METER_READING_READ,
            Permission.METER_READING_WRITE,
            # Reports
            Permission.REPORT_READ,
            Permission.REPORT_EXPORT,
            # Reminders
            Permission.REMINDER_READ,
            Permission.REMINDER_WRITE,
            # Caretaker management
            Permission.CARETAKER_READ,
            Permission.CARETAKER_WRITE,
            Permission.CARETAKER_REVOKE,
        }
    ),

    # ========================================================
    # CARETAKER
    # ========================================================
    #
    # Restricted operational access.
    #
    # Caretakers can:
    # - view operational property/unit information
    # - view tenants associated with assigned operations
    # - view payment information required for operations
    # - record offline payments
    # - enter water meter readings
    #
    # Caretakers cannot:
    # - create arbitrary payment transactions
    # - reverse payments
    # - assign payments
    # - export financial reports
    # - modify invoices
    # - manage other caretakers
    #
    # ========================================================
    Role.CARETAKER: frozenset(
        {
            Permission.PROPERTY_READ,
            Permission.UNIT_READ,
            Permission.TENANT_READ,
            # Payment visibility + offline collection logging
            Permission.PAYMENT_READ,
            Permission.OFFLINE_PAYMENT_CREATE,
            # Utility operations
            Permission.UTILITY_READ,
            # Meter operations
            Permission.METER_READING_READ,
            Permission.METER_READING_WRITE,
            Permission.CARETAKER_READ,
        }
    ),

    # ========================================================
    # TENANT
    # ========================================================
    #
    # Tenant access is intentionally limited.
    #
    # The tenant primarily interacts with the system through
    # M-Pesa, SMS, WhatsApp, and limited self-service endpoints.
    #
    # ========================================================
    Role.TENANT: frozenset(
        {
            Permission.UNIT_READ,
            Permission.TENANT_READ,
            Permission.INVOICE_READ,
            Permission.PAYMENT_READ,
            Permission.PAYMENT_CREATE,
            Permission.METER_READING_READ,
        }
    ),

    # ========================================================
    # ADMIN
    # ========================================================
    #
    # Platform-level administration.
    #
    # ========================================================
    Role.ADMIN: frozenset(Permission),

    # ========================================================
    # SYSTEM
    # ========================================================
    #
    # Internal trusted service operations.
    #
    # Keep this deliberately narrow.
    #
    # ========================================================
    Role.SYSTEM: frozenset(
        {
            Permission.PAYMENT_CREATE,
        }
    ),
}


# ============================================================
# Role Helpers
# ============================================================


def _normalize_role(role: Role | str) -> Role:
    """
    Convert a role value into the Role enum.

    Rejects unknown role values.
    """
    try:
        return role if isinstance(role, Role) else Role(role)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authorization role.",
        ) from exc


def get_role_permissions(
    role: Role | str,
) -> frozenset[Permission]:
    """
    Return all permissions granted to a role.
    """
    normalized_role = _normalize_role(role)
    permissions = ROLE_PERMISSIONS.get(normalized_role)

    if permissions is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No permissions configured for this role.",
        )

    return permissions


# ============================================================
# Permission Checks
# ============================================================


def has_permission(
    principal: Principal,
    permission: Permission,
) -> bool:
    """
    Return True when the principal has the requested permission.
    """
    permissions = get_role_permissions(principal.role)
    return permission in permissions


def require_permission(
    permission: Permission,
) -> AuthorizationDependency:
    """
    Create a FastAPI dependency that requires one permission.
    """

    async def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if not has_permission(principal, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}",
            )

        return principal

    return dependency


def require_all_permissions(
    *permissions: Permission,
) -> AuthorizationDependency:
    """
    Require the authenticated principal to have every
    supplied permission.
    """

    async def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        role_permissions = get_role_permissions(principal.role)

        missing_permissions = [
            permission
            for permission in permissions
            if permission not in role_permissions
        ]

        if missing_permissions:
            missing = ", ".join(
                permission.value
                for permission in missing_permissions
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permissions: {missing}",
            )

        return principal

    return dependency


def require_any_permission(
    *permissions: Permission,
) -> AuthorizationDependency:
    """
    Require the authenticated principal to have at least
    one of the supplied permissions.
    """

    async def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        role_permissions = get_role_permissions(principal.role)

        if not any(
            permission in role_permissions
            for permission in permissions
        ):
            required = ", ".join(
                permission.value
                for permission in permissions
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "At least one of these permissions is "
                    f"required: {required}"
                ),
            )

        return principal

    return dependency


def require_role_and_permission(
    role: Role,
    permission: Permission,
) -> AuthorizationDependency:
    """
    Require the authenticated principal to have both:
    1. The specified role.
    2. The specified permission.
    """

    async def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if not has_role(principal, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient role.",
            )

        if not has_permission(principal, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}",
            )

        return principal

    return dependency


# ============================================================
# Role Checks
# ============================================================


def has_role(
    principal: Principal,
    role: Role,
) -> bool:
    """
    Return True when the principal has the requested role.
    """
    try:
        principal_role = _normalize_role(principal.role)
    except HTTPException:
        return False

    return principal_role == role


def require_role(
    role: Role,
) -> AuthorizationDependency:
    """
    Create a FastAPI dependency requiring a specific role.
    """

    async def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if not has_role(principal, role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role.value}",
            )

        return principal

    return dependency


def require_any_role(
    *roles: Role,
) -> AuthorizationDependency:
    """
    Require the authenticated principal to have one of
    the supplied roles.
    """
    allowed_roles = set(roles)

    async def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        principal_role = _normalize_role(principal.role)

        if principal_role not in allowed_roles:
            allowed = ", ".join(
                role.value
                for role in roles
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of these roles is required: {allowed}",
            )

        return principal

    return dependency


# ============================================================
# Landlord Scope
# ============================================================


def require_landlord_context(
    principal: Principal,
) -> str:
    """
    Return the landlord scope associated with the principal.

    Landlord-scoped operations must have a valid landlord ID.
    """
    if not principal.landlord_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Landlord scope is required.",
        )

    return principal.landlord_id


def require_landlord_scope(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """
    Require an authenticated principal to have a landlord scope.
    """
    require_landlord_context(principal)
    return principal
