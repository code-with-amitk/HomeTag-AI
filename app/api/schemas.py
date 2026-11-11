"""
> Why: Define validated external request and response schemas for identity and inventory APIs.
> Throughput: Validation occurs at API boundaries for each request and response.
> Dependencies: Pydantic 2.x.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

NonEmptyName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=160),
]
OptionalShortText = Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=240)]
CountryCode = Annotated[
    str | None, StringConstraints(strip_whitespace=True, min_length=2, max_length=2)
]
ServiceDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=4000),
]
PublicQRField = Literal[
    "name",
    "make",
    "model",
    "warranty_expiry",
    "technician_contact",
    "service_history",
]


class QRTagCreate(BaseModel):
    """Fields that an owner explicitly approves for anonymous QR display."""

    public_fields: list[PublicQRField] = Field(
        default_factory=list,
        description="Allowlisted appliance fields to expose on the public QR page.",
    )


class QRTagUpdate(BaseModel):
    """Updated public fields for an existing QR tag."""

    public_fields: list[PublicQRField] = Field(
        description="Complete allowlist of appliance fields to expose publicly."
    )


class QRTagRead(BaseModel):
    """QR tag details returned to an authorized household member."""

    tag_id: str = Field(description="Opaque public tag identifier.")
    scan_path: str = Field(description="Public scan URL path for this tag.")
    is_active: bool = Field(description="Whether the tag currently resolves.")
    public_fields: list[PublicQRField] = Field(
        description="Fields explicitly approved for the public scan page."
    )


class RegisterRequest(BaseModel):
    """Self-service registration details."""

    email: EmailStr = Field(description="Account email address; normalized to lowercase.")
    password: str = Field(min_length=12, max_length=128, description="Account password.")
    household_name: NonEmptyName = Field(description="Name for the new household.")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        """Normalize email addresses for case-insensitive account identity."""
        return str(value).strip().lower()


class HouseholdMemberCreate(BaseModel):
    """Request to add an existing account to an owned household."""

    email: EmailStr = Field(description="Email address of the existing account to add.")


class HouseholdMemberRead(BaseModel):
    """Safe household member representation."""

    user_id: UUID = Field(description="Account identifier.")
    email: EmailStr = Field(description="Member email address.")
    role: str = Field(description="Household role.")


class UserRead(BaseModel):
    """Safe account representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Account identifier.")
    email: str = Field(description="Normalized account email address.")
    is_active: bool = Field(description="Whether the account can authenticate.")
    created_at: datetime = Field(description="Account creation timestamp.")


class HouseholdRead(BaseModel):
    """Household representation for the authenticated account."""

    id: UUID = Field(description="Tenant identifier.")
    name: str = Field(description="Household display name.")
    role: str = Field(description="Current account's household role.")


class RegistrationResponse(BaseModel):
    """New account and household identifiers."""

    user: UserRead = Field(description="Created account.")
    household: HouseholdRead = Field(description="Created household and owner membership.")


class TokenResponse(BaseModel):
    """OAuth2 bearer access token response."""

    access_token: str = Field(description="Signed short-lived access token.")
    token_type: str = Field(default="bearer", description="Authorization scheme.")
    expires_in: int = Field(description="Token lifetime in seconds.")


class AuthenticatedUserRead(UserRead):
    """Account and its active household memberships."""

    households: list[HouseholdRead] = Field(description="Households this account can access.")


class PropertyCreate(BaseModel):
    """Fields required to create a household property."""

    household_id: UUID = Field(description="Household that owns the property.")
    name: NonEmptyName = Field(description="Property display name.")
    address_line: OptionalShortText = Field(default=None, description="Street address.")
    city: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = Field(
        default=None, description="City or locality."
    )
    region: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = Field(
        default=None, description="State, province, or region."
    )
    postal_code: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=32)] = (
        Field(default=None, description="Postal or ZIP code.")
    )
    country: CountryCode = Field(default=None, description="Two-letter country code.")


class PropertyUpdate(BaseModel):
    """Fields that can be changed on an existing property."""

    name: NonEmptyName | None = Field(default=None, description="Updated property display name.")
    address_line: OptionalShortText = Field(default=None, description="Updated street address.")
    city: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = Field(
        default=None, description="Updated city or locality."
    )
    region: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = Field(
        default=None, description="Updated state, province, or region."
    )
    postal_code: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=32)] = (
        Field(default=None, description="Updated postal or ZIP code.")
    )
    country: CountryCode = Field(default=None, description="Updated two-letter country code.")


class PropertyRead(BaseModel):
    """Property representation returned to household members."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Property identifier.")
    household_id: UUID = Field(description="Owning household identifier.")
    name: str = Field(description="Property display name.")
    address_line: str | None = Field(description="Street address.")
    city: str | None = Field(description="City or locality.")
    region: str | None = Field(description="State, province, or region.")
    postal_code: str | None = Field(description="Postal or ZIP code.")
    country: str | None = Field(description="Two-letter country code.")
    created_at: datetime = Field(description="Property creation timestamp.")
    updated_at: datetime = Field(description="Last property update timestamp.")


class ApplianceCreate(BaseModel):
    """Fields required to create an appliance in an accessible property."""

    property_id: UUID = Field(description="Owning property identifier.")
    name: NonEmptyName = Field(description="Appliance display name.")
    make: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = Field(
        default=None, description="Manufacturer or make."
    )
    model: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = Field(
        default=None, description="Model identifier."
    )
    serial_number: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=160)
    ] = Field(default=None, description="Private appliance serial number.")
    purchase_date: date | None = Field(default=None, description="Purchase date.")
    warranty_expiry: date | None = Field(default=None, description="Warranty expiration date.")


class ApplianceUpdate(BaseModel):
    """Fields that can be changed on an existing appliance."""

    name: NonEmptyName | None = Field(default=None, description="Updated appliance display name.")
    make: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = Field(
        default=None, description="Updated manufacturer or make."
    )
    model: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=120)] = Field(
        default=None, description="Updated model identifier."
    )
    serial_number: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=160)
    ] = Field(default=None, description="Updated private serial number.")
    purchase_date: date | None = Field(default=None, description="Updated purchase date.")
    warranty_expiry: date | None = Field(default=None, description="Updated warranty expiration.")


class ApplianceRead(BaseModel):
    """Appliance representation returned to authorized household members."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Appliance identifier.")
    property_id: UUID = Field(description="Owning property identifier.")
    name: str = Field(description="Appliance display name.")
    make: str | None = Field(description="Manufacturer or make.")
    model: str | None = Field(description="Model identifier.")
    serial_number: str | None = Field(description="Private appliance serial number.")
    purchase_date: date | None = Field(description="Purchase date.")
    warranty_expiry: date | None = Field(description="Warranty expiration date.")
    status: str = Field(description="Appliance lifecycle status.")
    created_at: datetime = Field(description="Appliance creation timestamp.")
    updated_at: datetime = Field(description="Last appliance update timestamp.")


class TechnicianCreate(BaseModel):
    """Fields required to create a household technician contact."""

    household_id: UUID = Field(description="Household that owns the technician entry.")
    name: NonEmptyName = Field(description="Technician display name.")
    phone: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=40)] = Field(
        default=None, description="Technician phone number."
    )
    email: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=320)] = Field(
        default=None, description="Technician email address."
    )
    organization: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=160)
    ] = Field(default=None, description="Technician organization.")


class TechnicianUpdate(BaseModel):
    """Fields that can be changed on a household technician contact."""

    name: NonEmptyName | None = Field(default=None, description="Updated display name.")
    phone: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=40)] = Field(
        default=None, description="Updated phone number."
    )
    email: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=320)] = Field(
        default=None, description="Updated email address."
    )
    organization: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=160)
    ] = Field(default=None, description="Updated organization.")


class TechnicianRead(BaseModel):
    """Household-private technician directory entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Technician identifier.")
    household_id: UUID = Field(description="Owning household identifier.")
    name: str = Field(description="Technician display name.")
    phone: str | None = Field(description="Technician phone number.")
    email: str | None = Field(description="Technician email address.")
    organization: str | None = Field(description="Technician organization.")
    is_active: bool = Field(description="Whether the directory entry is active.")
    created_at: datetime = Field(description="Technician entry creation timestamp.")
    updated_at: datetime = Field(description="Last technician entry update timestamp.")


class ServiceRecordCreate(BaseModel):
    """Fields required to add an appliance service event."""

    serviced_at: date = Field(description="Date the service was performed.")
    description: ServiceDescription = Field(description="Description of work performed.")
    technician_id: UUID | None = Field(default=None, description="Optional household technician.")
    cost: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2,
        description="Optional service cost.",
    )
    is_public: bool = Field(
        default=False,
        description="Whether this record may appear on a public QR page.",
    )


class ServiceRecordRead(BaseModel):
    """Appliance service history entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(description="Service record identifier.")
    appliance_id: UUID = Field(description="Appliance identifier.")
    technician_id: UUID | None = Field(description="Associated technician identifier.")
    serviced_at: date = Field(description="Date the service was performed.")
    description: str = Field(description="Description of work performed.")
    cost: Decimal | None = Field(description="Service cost.")
    is_public: bool = Field(description="Whether this record may appear on a public QR page.")
    created_at: datetime = Field(description="Service record creation timestamp.")


class ServiceRecordUpdate(BaseModel):
    """Fields that can be corrected on an existing service event."""

    serviced_at: date | None = Field(default=None, description="Corrected service date.")
    description: ServiceDescription | None = Field(
        default=None, description="Corrected description of work performed."
    )
    technician_id: UUID | None = Field(
        default=None, description="Updated technician, or null to remove attribution."
    )
    cost: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2,
        description="Corrected service cost.",
    )
    is_public: bool | None = Field(
        default=None,
        description="Whether this record may appear on a public QR page.",
    )


class MessageResponse(BaseModel):
    """Simple successful operation response."""

    message: str = Field(description="Outcome of the requested operation.")
