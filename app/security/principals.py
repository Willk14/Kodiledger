from __future__ import annotations

from dataclasses import dataclass

from app.security.roles import Role


@dataclass(frozen=True)
class Principal:
    """
    Represents the authenticated identity making a request.
    """

    user_id: str
    role: Role
    landlord_id: str | None = None