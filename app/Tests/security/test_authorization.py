from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.security.authorization import (
    ROLE_PERMISSIONS,
    get_role_permissions,
    has_permission,
    has_role,
    require_all_permissions,
    require_any_permission,
    require_any_role,
    require_landlord_context,
    require_landlord_scope,
    require_permission,
    require_role,
)
from app.security.permissions import Permission
from app.security.principals import Principal
from app.security.roles import Role


# ============================================================
# Test Principals
# ============================================================

LANDLORD = Principal(
    user_id="landlord-user",
    role=Role.LANDLORD,
    landlord_id="landlord-001",
)

CARETAKER = Principal(
    user_id="caretaker-user",
    role=Role.CARETAKER,
    landlord_id="landlord-001",
)

TENANT = Principal(
    user_id="tenant-user",
    role=Role.TENANT,
    landlord_id="landlord-001",
)

ADMIN = Principal(
    user_id="admin-user",
    role=Role.ADMIN,
)

SYSTEM = Principal(
    user_id="system-user",
    role=Role.SYSTEM,
)


# ============================================================
# Role Matrix
# ============================================================

def test_all_roles_are_configured() -> None:
    assert set(ROLE_PERMISSIONS) == {
        Role.LANDLORD,
        Role.CARETAKER,
        Role.TENANT,
        Role.ADMIN,
        Role.SYSTEM,
    }


def test_landlord_permissions() -> None:
    expected_permissions = {
        Permission.PROPERTY_READ,
        Permission.PROPERTY_WRITE,
        Permission.UNIT_READ,
        Permission.UNIT_WRITE,
        Permission.TENANT_READ,
        Permission.TENANT_WRITE,
        Permission.INVOICE_READ,
        Permission.INVOICE_WRITE,
        Permission.PAYMENT_READ,
        Permission.PAYMENT_CREATE,
        Permission.PAYMENT_REVERSE,
        Permission.PAYMENT_ASSIGN,
        Permission.OFFLINE_PAYMENT_CREATE,
        Permission.UTILITY_READ,
        Permission.UTILITY_WRITE,
        Permission.METER_READING_READ,
        Permission.METER_READING_WRITE,
        Permission.REPORT_READ,
        Permission.REPORT_EXPORT,
        Permission.REMINDER_READ,
        Permission.REMINDER_WRITE,
        Permission.CARETAKER_READ,
        Permission.CARETAKER_WRITE,
        Permission.CARETAKER_REVOKE,
    }

    assert expected_permissions.issubset(
        ROLE_PERMISSIONS[Role.LANDLORD]
    )


def test_caretaker_has_operational_permissions() -> None:
    assert has_permission(
        CARETAKER,
        Permission.PROPERTY_READ,
    )

    assert has_permission(
        CARETAKER,
        Permission.UNIT_READ,
    )

    assert has_permission(
        CARETAKER,
        Permission.TENANT_READ,
    )

    assert has_permission(
        CARETAKER,
        Permission.PAYMENT_READ,
    )

    assert has_permission(
        CARETAKER,
        Permission.OFFLINE_PAYMENT_CREATE,
    )

    assert has_permission(
        CARETAKER,
        Permission.METER_READING_READ,
    )

    assert has_permission(
        CARETAKER,
        Permission.METER_READING_WRITE,
    )


def test_caretaker_cannot_access_sensitive_operations() -> None:
    forbidden_permissions = {
        Permission.PROPERTY_WRITE,
        Permission.UNIT_WRITE,
        Permission.TENANT_WRITE,
        Permission.INVOICE_WRITE,
        Permission.PAYMENT_CREATE,
        Permission.PAYMENT_REVERSE,
        Permission.PAYMENT_ASSIGN,
        Permission.UTILITY_WRITE,
        Permission.REPORT_EXPORT,
        Permission.REMINDER_WRITE,
        Permission.CARETAKER_WRITE,
        Permission.CARETAKER_REVOKE,
    }

    for permission in forbidden_permissions:
        assert not has_permission(
            CARETAKER,
            permission,
        )


def test_tenant_has_limited_access() -> None:
    assert has_permission(
        TENANT,
        Permission.INVOICE_READ,
    )

    assert has_permission(
        TENANT,
        Permission.PAYMENT_READ,
    )

    assert has_permission(
        TENANT,
        Permission.PAYMENT_CREATE,
    )


def test_tenant_cannot_modify_landlord_data() -> None:
    assert not has_permission(
        TENANT,
        Permission.PROPERTY_WRITE,
    )

    assert not has_permission(
        TENANT,
        Permission.TENANT_WRITE,
    )

    assert not has_permission(
        TENANT,
        Permission.INVOICE_WRITE,
    )

    assert not has_permission(
        TENANT,
        Permission.PAYMENT_REVERSE,
    )


def test_admin_has_all_permissions() -> None:
    for permission in Permission:
        assert has_permission(
            ADMIN,
            permission,
        )


def test_system_has_limited_permissions() -> None:
    assert has_permission(
        SYSTEM,
        Permission.PAYMENT_CREATE,
    )

    assert not has_permission(
        SYSTEM,
        Permission.TENANT_WRITE,
    )

    assert not has_permission(
        SYSTEM,
        Permission.REPORT_EXPORT,
    )


# ============================================================
# Role Helpers
# ============================================================

def test_has_role() -> None:
    assert has_role(
        LANDLORD,
        Role.LANDLORD,
    )

    assert not has_role(
        LANDLORD,
        Role.CARETAKER,
    )


def test_get_role_permissions() -> None:
    permissions = get_role_permissions(
        Role.CARETAKER
    )

    assert (
        Permission.METER_READING_WRITE
        in permissions
    )

    assert (
        Permission.OFFLINE_PAYMENT_CREATE
        in permissions
    )

    assert (
        Permission.PAYMENT_REVERSE
        not in permissions
    )


def test_invalid_role_is_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        get_role_permissions("INVALID_ROLE")

    assert exc_info.value.status_code == 403


# ============================================================
# Permission Dependencies
# ============================================================

@pytest.mark.asyncio
async def test_require_permission_allows_access() -> None:
    dependency = require_permission(
        Permission.INVOICE_READ
    )

    result = await dependency(LANDLORD)

    assert result == LANDLORD


@pytest.mark.asyncio
async def test_require_permission_rejects_access() -> None:
    dependency = require_permission(
        Permission.INVOICE_WRITE
    )

    with pytest.raises(HTTPException) as exc_info:
        await dependency(CARETAKER)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_all_permissions_allows_access() -> None:
    dependency = require_all_permissions(
        Permission.INVOICE_READ,
        Permission.INVOICE_WRITE,
    )

    result = await dependency(LANDLORD)

    assert result == LANDLORD


@pytest.mark.asyncio
async def test_require_all_permissions_rejects_missing_permission() -> None:
    dependency = require_all_permissions(
        Permission.INVOICE_READ,
        Permission.INVOICE_WRITE,
    )

    with pytest.raises(HTTPException) as exc_info:
        await dependency(CARETAKER)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_any_permission_allows_access() -> None:
    dependency = require_any_permission(
        Permission.INVOICE_WRITE,
        Permission.METER_READING_WRITE,
    )

    result = await dependency(CARETAKER)

    assert result == CARETAKER


@pytest.mark.asyncio
async def test_require_any_permission_rejects_access() -> None:
    dependency = require_any_permission(
        Permission.INVOICE_WRITE,
        Permission.PAYMENT_REVERSE,
    )

    with pytest.raises(HTTPException) as exc_info:
        await dependency(CARETAKER)

    assert exc_info.value.status_code == 403


# ============================================================
# Role Dependencies
# ============================================================

@pytest.mark.asyncio
async def test_require_role_allows_correct_role() -> None:
    dependency = require_role(
        Role.LANDLORD
    )

    result = await dependency(LANDLORD)

    assert result == LANDLORD


@pytest.mark.asyncio
async def test_require_role_rejects_wrong_role() -> None:
    dependency = require_role(
        Role.LANDLORD
    )

    with pytest.raises(HTTPException) as exc_info:
        await dependency(CARETAKER)

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_require_any_role_allows_matching_role() -> None:
    dependency = require_any_role(
        Role.LANDLORD,
        Role.ADMIN,
    )

    assert await dependency(LANDLORD) == LANDLORD
    assert await dependency(ADMIN) == ADMIN


@pytest.mark.asyncio
async def test_require_any_role_rejects_wrong_role() -> None:
    dependency = require_any_role(
        Role.LANDLORD,
        Role.ADMIN,
    )

    with pytest.raises(HTTPException) as exc_info:
        await dependency(TENANT)

    assert exc_info.value.status_code == 403


# ============================================================
# Landlord Scope
# ============================================================

def test_require_landlord_context() -> None:
    assert (
        require_landlord_context(LANDLORD)
        == "landlord-001"
    )


def test_require_landlord_context_rejects_missing_scope() -> None:
    principal = Principal(
        user_id="no-scope-user",
        role=Role.LANDLORD,
        landlord_id=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        require_landlord_context(principal)

    assert exc_info.value.status_code == 403


def test_require_landlord_scope() -> None:
    result = require_landlord_scope(
        LANDLORD
    )

    assert result == LANDLORD

    
