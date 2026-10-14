from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_user import AppUser
from app.models.user_membership import UserMembership
from app.security.authentication import AuthenticationError, OIDCIdentity
from app.security.principals import AuthenticatedContext
from app.security.roles import Role


class IdentityAuthorizationError(Exception):
    """Raised when an authenticated identity has no usable membership."""


async def resolve_authenticated_context(
    db: AsyncSession,
    identity: OIDCIdentity,
) -> AuthenticatedContext:
    """Resolve a verified provider identity into KodiLedger-owned authority."""
    statement = (
        select(AppUser, UserMembership)
        .outerjoin(UserMembership, UserMembership.user_id == AppUser.id)
        .where(
            AppUser.identity_issuer == identity.issuer,
            AppUser.identity_subject == identity.subject,
        )
    )
    rows = (await db.execute(statement)).all()

    if not rows:
        raise AuthenticationError("Identity is not linked to a KodiLedger account.")

    user = rows[0][0]
    if not user.is_active:
        raise AuthenticationError("Identity is not linked to an active account.")

    active_memberships: list[tuple[UserMembership, Role]] = []
    for _, membership in rows:
        if membership is None or not membership.is_active:
            continue
        try:
            role = Role(membership.role)
        except (ValueError, TypeError) as exc:
            raise IdentityAuthorizationError(
                "An active membership has an unsupported role."
            ) from exc
        if role is Role.SYSTEM:
            raise IdentityAuthorizationError(
                "System identity cannot be used for a bearer request."
            )
        active_memberships.append((membership, role))

    if not active_memberships:
        raise IdentityAuthorizationError(
            "No active KodiLedger membership is assigned to this identity."
        )
    if len(active_memberships) != 1:
        raise IdentityAuthorizationError(
            "This identity has multiple active memberships; membership selection is not available."
        )

    membership, role = active_memberships[0]
    landlord_id = (
        str(membership.landlord_id)
        if membership.landlord_id is not None
        else None
    )
    tenant_id = str(membership.tenant_id) if membership.tenant_id is not None else None

    if role in (Role.LANDLORD, Role.CARETAKER) and landlord_id is None:
        raise IdentityAuthorizationError("Landlord scope is missing from membership.")
    if role is Role.TENANT and (landlord_id is None or tenant_id is None):
        raise IdentityAuthorizationError("Tenant scope is missing from membership.")
    if role is Role.ADMIN and (landlord_id is not None or tenant_id is not None):
        raise IdentityAuthorizationError("Administrator membership has invalid scope.")
    if role is not Role.TENANT and tenant_id is not None:
        raise IdentityAuthorizationError("Non-tenant membership has invalid tenant scope.")

    return AuthenticatedContext(
        user_id=str(user.id),
        role=role,
        landlord_id=landlord_id,
        tenant_id=tenant_id,
    )
