"""
> Why: Resolve authenticated identities and enforce household ownership boundaries.
> Throughput: One indexed membership lookup per authorized route operation.
> Dependencies: FastAPI security, SQLAlchemy, application settings, and JWT validation.
"""

from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import decode_access_token
from app.db.models import HouseholdMembership, MembershipRole, User
from app.db.session import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/token")
DbSession = Annotated[Session, Depends(get_db)]
BearerToken = Annotated[str, Depends(oauth2_scheme)]


def get_current_user(request: Request, token: BearerToken, db: DbSession) -> User:
    """Validate the bearer token and resolve an active account."""
    settings: Settings = request.app.state.settings
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "invalid_credentials", "message": "Authentication is required."},
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        user_id = decode_access_token(token, settings)
    except (jwt.InvalidTokenError, ValueError):
        raise unauthorized from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    return user


AuthenticatedUser = Annotated[User, Depends(get_current_user)]


def require_membership(
    db: Session,
    user: User,
    household_id: UUID,
    *,
    owner_only: bool = False,
) -> HouseholdMembership:
    """Return an active household membership or hide the tenant from the caller."""
    query = select(HouseholdMembership).where(
        HouseholdMembership.user_id == user.id,
        HouseholdMembership.household_id == household_id,
        HouseholdMembership.is_active.is_(True),
    )
    membership = db.scalar(query)
    if membership is None or (owner_only and membership.role != MembershipRole.OWNER.value):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Resource not found."},
        )
    return membership


def accessible_household_ids(db: Session, user: User) -> list[UUID]:
    """Return identifiers for the user's active tenant memberships."""
    return list(
        db.scalars(
            select(HouseholdMembership.household_id).where(
                HouseholdMembership.user_id == user.id,
                HouseholdMembership.is_active.is_(True),
            )
        )
    )
