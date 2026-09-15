from unittest.mock import AsyncMock

import pytest

from app.security.principals import Principal
from app.security.rls import set_rls_context
from app.security.roles import Role


@pytest.mark.asyncio
async def test_set_rls_context_sets_landlord_user_and_role():
    db = AsyncMock()

    principal = Principal(
        user_id="landlord-user",
        role=Role.LANDLORD,
        landlord_id="11111111-1111-1111-1111-111111111111",
    )

    await set_rls_context(
        db=db,
        principal=principal,
    )

    db.execute.assert_awaited_once()

    statement = db.execute.await_args.args[0]

    statement_text = str(statement)

    assert "app.current_landlord_id" in statement_text
    assert "app.current_user_id" in statement_text
    assert "app.current_role" in statement_text

    params = db.execute.await_args.args[1]

    assert params["landlord_id"] == (
        "11111111-1111-1111-1111-111111111111"
    )
    assert params["user_id"] == "landlord-user"
    assert params["role"] == "LANDLORD"


@pytest.mark.asyncio
async def test_set_rls_context_allows_principal_without_landlord_id():
    db = AsyncMock()

    principal = Principal(
        user_id="system-user",
        role=Role.SYSTEM,
        landlord_id=None,
    )

    await set_rls_context(
        db=db,
        principal=principal,
    )

    params = db.execute.await_args.args[1]

    assert params["landlord_id"] == ""
    assert params["user_id"] == "system-user"
    assert params["role"] == "SYSTEM"

    