"""
> Why: Register accounts, authenticate credentials, and manage household access.
> Throughput: Login performs one indexed account lookup and a password hash check.
> Dependencies: FastAPI, SQLAlchemy, Argon2, and signed bearer tokens.
"""

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import AuthenticatedUser, DbSession, require_membership
from app.api.schemas import (
    AuthenticatedUserRead,
    HouseholdMemberCreate,
    HouseholdMemberRead,
    HouseholdRead,
    MessageResponse,
    RegisterRequest,
    RegistrationResponse,
    TokenResponse,
    UserRead,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.db.models import Household, HouseholdMembership, MembershipRole, User

router = APIRouter(prefix="/v1", tags=["identity"])


@router.post(
    "/auth/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an account and household",
)
def register(payload: RegisterRequest, db: DbSession) -> RegistrationResponse:
    """Create an account, its first household, and an owner membership."""
    user = User(email=str(payload.email).lower(), password_hash=hash_password(payload.password))
    household = Household(name=payload.household_name)
    db.add_all([user, household])
    try:
        db.flush()
        db.add(
            HouseholdMembership(
                household_id=household.id,
                user_id=user.id,
                role=MembershipRole.OWNER.value,
                is_active=True,
            )
        )
        db.commit()
        db.refresh(user)
        db.refresh(household)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "email_already_registered",
                "message": "An account already uses this email.",
            },
        ) from None
    return RegistrationResponse(
        user=UserRead.model_validate(user),
        household=HouseholdRead(
            id=household.id,
            name=household.name,
            role=MembershipRole.OWNER.value,
        ),
    )


@router.post(
    "/auth/token",
    response_model=TokenResponse,
    summary="Exchange credentials for a bearer access token",
)
def create_token(
    request: Request,
    db: DbSession,
    form: OAuth2PasswordRequestForm = Depends(),
) -> TokenResponse:
    """Authenticate email/password credentials and issue a short-lived access token."""
    email = form.username.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(form.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "Email or password is incorrect."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    settings = request.app.state.settings
    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=int(timedelta(minutes=settings.access_token_minutes).total_seconds()),
    )


@router.get("/me", response_model=AuthenticatedUserRead, summary="Read the authenticated account")
def read_me(user: AuthenticatedUser, db: DbSession) -> AuthenticatedUserRead:
    """Return account details and active household roles without credential data."""
    memberships = db.execute(
        select(HouseholdMembership, Household)
        .join(Household, Household.id == HouseholdMembership.household_id)
        .where(
            HouseholdMembership.user_id == user.id,
            HouseholdMembership.is_active.is_(True),
        )
    ).all()
    return AuthenticatedUserRead(
        id=user.id,
        email=user.email,
        is_active=user.is_active,
        created_at=user.created_at,
        households=[
            HouseholdRead(id=household.id, name=household.name, role=membership.role)
            for membership, household in memberships
        ],
    )


@router.get(
    "/households/{household_id}/members",
    response_model=list[HouseholdMemberRead],
    summary="List household members",
)
def list_members(
    household_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
) -> list[HouseholdMemberRead]:
    """List household members for an owner."""
    require_membership(db, user, household_id, owner_only=True)
    rows = db.execute(
        select(User.id, User.email, HouseholdMembership.role)
        .join(HouseholdMembership, HouseholdMembership.user_id == User.id)
        .where(
            HouseholdMembership.household_id == household_id,
            HouseholdMembership.is_active.is_(True),
        )
        .order_by(User.email)
    )
    return [HouseholdMemberRead(user_id=row.id, email=row.email, role=row.role) for row in rows]


@router.post(
    "/households/{household_id}/members",
    response_model=HouseholdMemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add an existing account to a household",
)
def add_member(
    household_id: UUID,
    payload: HouseholdMemberCreate,
    user: AuthenticatedUser,
    db: DbSession,
) -> HouseholdMemberRead:
    """Allow an owner to add an existing account as a household member."""
    require_membership(db, user, household_id, owner_only=True)
    member = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if member is None or not member.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Resource not found."},
        )
    existing = db.scalar(
        select(HouseholdMembership).where(
            HouseholdMembership.household_id == household_id,
            HouseholdMembership.user_id == member.id,
        )
    )
    if existing is not None:
        if existing.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "already_a_member",
                    "message": "Account is already a household member.",
                },
            )
        existing.is_active = True
        existing.role = MembershipRole.MEMBER.value
        membership = existing
    else:
        membership = HouseholdMembership(
            household_id=household_id,
            user_id=member.id,
            role=MembershipRole.MEMBER.value,
            is_active=True,
        )
        db.add(membership)
    db.commit()
    return HouseholdMemberRead(user_id=member.id, email=member.email, role=membership.role)


@router.delete(
    "/households/{household_id}/members/{member_user_id}",
    response_model=MessageResponse,
    summary="Remove a household member",
)
def remove_member(
    household_id: UUID,
    member_user_id: UUID,
    user: AuthenticatedUser,
    db: DbSession,
) -> MessageResponse:
    """Allow an owner to remove a member without deleting their account."""
    require_membership(db, user, household_id, owner_only=True)
    membership = db.scalar(
        select(HouseholdMembership).where(
            HouseholdMembership.household_id == household_id,
            HouseholdMembership.user_id == member_user_id,
            HouseholdMembership.is_active.is_(True),
            HouseholdMembership.role == MembershipRole.MEMBER.value,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Resource not found."},
        )
    membership.is_active = False
    db.commit()
    return MessageResponse(message="Household member removed.")
