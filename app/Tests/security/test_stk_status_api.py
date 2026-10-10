from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.v1.endpoints.payments as payments_module
from app.core.database import get_system_db
from app.security.dependencies import get_current_principal
from app.security.principals import AuthenticatedContext
from app.security.roles import Role


class FakeStkRepository:
    def __init__(self, _db):
        self.callback_received = False
        self.list_unresolved = AsyncMock()
        self.get_by_checkout_id = AsyncMock()
        self.record_query = AsyncMock(side_effect=self._record_query)
        self.record_query_error = AsyncMock()

    async def _record_query(self, _checkout_id, _response):
        return "CALLBACK_RECEIVED" if self.callback_received else "SUCCEEDED"


@pytest.fixture
def recovery_api(monkeypatch):
    test_app = FastAPI()
    test_app.include_router(payments_module.router, prefix="/api/v1")
    state = {
        "principal": AuthenticatedContext(
            user_id="operator", role=Role.ADMIN, landlord_id=None
        )
    }
    test_app.dependency_overrides[get_current_principal] = lambda: state["principal"]

    db = AsyncMock()

    async def system_db():
        yield db

    test_app.dependency_overrides[get_system_db] = system_db
    repository = FakeStkRepository(db)
    monkeypatch.setattr(
        payments_module, "StkPushRequestRepository", lambda _db: repository
    )
    return TestClient(test_app), state, repository, db


def test_unresolved_queue_denies_non_admin_and_is_paginated(recovery_api):
    client, state, repository, db = recovery_api
    created = datetime(2026, 1, 2, tzinfo=timezone.utc)
    repository.list_unresolved.return_value = (
        [
            {
                "id": uuid4(),
                "checkout_request_id": "ws_CO_TEST_001",
                "request_status": "QUERY_ACCEPTED",
                "query_count": 2,
                "created_at": created,
                "last_queried_at": None,
            }
        ],
        1,
    )

    state["principal"] = AuthenticatedContext(
        user_id="landlord", role=Role.LANDLORD, landlord_id=str(uuid4())
    )
    denied = client.get("/api/v1/payments/stk-push/unresolved")
    assert denied.status_code == 403

    state["principal"] = AuthenticatedContext(
        user_id="operator", role=Role.ADMIN, landlord_id=None
    )
    response = client.get(
        "/api/v1/payments/stk-push/unresolved?limit=10&offset=5"
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "QUERY_ACCEPTED"
    assert response.json()["items"][0]["last_queried_at"] is None
    assert response.json()["total"] == 1
    assert response.json()["limit"] == 10
    assert response.json()["offset"] == 5
    repository.list_unresolved.assert_awaited_once_with(limit=10, offset=5)
    db.commit.assert_awaited_once()


def test_query_audit_preserves_callback_that_arrives_during_request(
    recovery_api, monkeypatch
):
    client, _state, repository, db = recovery_api
    repository.get_by_checkout_id.return_value = {
        "callback_received_at": None,
    }

    async def provider_query(_checkout_id):
        repository.callback_received = True
        return {"ResponseCode": "0", "ResultCode": "0", "ResultDesc": "Success"}

    monkeypatch.setattr(
        payments_module.payment_initiation_service,
        "query_mpesa_stk_push",
        AsyncMock(side_effect=provider_query),
    )

    response = client.post(
        "/api/v1/payments/stk-push/ws_CO_TEST_001/query"
    )

    assert response.status_code == 200
    assert response.json()["status"] == "CALLBACK_RECEIVED"
    repository.record_query.assert_awaited_once()
    assert db.commit.await_count == 2


def test_status_query_queue_rejects_invalid_page_size(recovery_api):
    client, _state, repository, _db = recovery_api

    response = client.get(
        "/api/v1/payments/stk-push/unresolved?limit=101"
    )

    assert response.status_code == 422
    repository.list_unresolved.assert_not_awaited()
