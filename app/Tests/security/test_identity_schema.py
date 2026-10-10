from app.models.app_user import AppUser
from app.models.user_membership import UserMembership


def test_external_identity_is_unique_per_issuer_and_subject() -> None:
    constraint_names = {item.name for item in AppUser.__table__.constraints}

    assert "uq_app_users_identity" in constraint_names


def test_membership_schema_excludes_system_and_requires_role_scope() -> None:
    constraints = {
        item.name: str(item.sqltext)
        for item in UserMembership.__table__.constraints
        if getattr(item, "sqltext", None) is not None
    }

    assert "ck_user_memberships_application_role" in constraints
    assert "'SYSTEM'" not in constraints["ck_user_memberships_application_role"]
    assert "ck_user_memberships_role_scope" in constraints


def test_tenant_membership_checks_tenant_and_landlord_as_a_pair() -> None:
    foreign_keys = {
        item.name: {(element.parent.name, element.target_fullname) for element in item.elements}
        for item in UserMembership.__table__.constraints
        if getattr(item, "elements", None)
    }

    assert foreign_keys["fk_user_memberships_tenant_landlord"] == {
        ("tenant_id", "tenants.id"),
        ("landlord_id", "tenants.landlord_id"),
    }
