"""Administrator web-session endpoints: members, invitations, credentials, master key."""

from fastapi import APIRouter, Depends, Request

from maestro.api.deps import maestro, ok, principal
from maestro.api.models import (
    AuditEvent,
    Credential,
    CredentialCreate,
    CredentialValue,
    Envelope,
    Invitation,
    InvitationCreate,
    IssuedInvitation,
    MasterKeyRotation,
    MasterKeyStatus,
    StatusChange,
    User,
)
from maestro.domain.states import Role, UserStatus
from maestro.services import audit_queries
from maestro.services.principal import Principal

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/members", response_model=Envelope[list[User]])
def members(request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).accounts.list_members(who))


@router.post("/members/{user_id}/disable", response_model=Envelope[User])
def disable(
    user_id: str, body: StatusChange, request: Request, who: Principal = Depends(principal)
):
    service = maestro(request).accounts
    return ok(
        request, service.set_status(who, user_id, UserStatus.DISABLED, body.expected_revision)
    )


@router.post("/members/{user_id}/enable", response_model=Envelope[User])
def enable(user_id: str, body: StatusChange, request: Request, who: Principal = Depends(principal)):
    service = maestro(request).accounts
    return ok(request, service.set_status(who, user_id, UserStatus.ACTIVE, body.expected_revision))


@router.post(
    "/members/{user_id}/password-reset",
    response_model=Envelope[IssuedInvitation],
    status_code=201,
)
def password_reset(user_id: str, request: Request, who: Principal = Depends(principal)):
    service = maestro(request).accounts
    return ok(
        request,
        service.create_invitation(who, Role.MEMBER, "password reset", target_user_id=user_id),
    )


@router.get("/invitations", response_model=Envelope[list[Invitation]])
def invitations(request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).accounts.list_invitations(who))


@router.post("/invitations", response_model=Envelope[IssuedInvitation], status_code=201)
def invite(body: InvitationCreate, request: Request, who: Principal = Depends(principal)):
    service = maestro(request).accounts
    return ok(request, service.create_invitation(who, Role(body.role), body.note, body.valid_hours))


@router.post("/invitations/{invitation_id}/revoke", response_model=Envelope[Invitation])
def revoke_invitation(invitation_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).accounts.revoke_invitation(who, invitation_id))


@router.get("/credentials", response_model=Envelope[list[Credential]])
def credentials(request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).credentials.list(who))


@router.post("/credentials", response_model=Envelope[Credential], status_code=201)
def create_credential(
    body: CredentialCreate, request: Request, who: Principal = Depends(principal)
):
    service = maestro(request).credentials
    return ok(
        request,
        service.create(who, body.name, body.kind, body.provider, body.description, body.value),
    )


@router.put("/credentials/{credential_id}/value", response_model=Envelope[Credential])
def replace_value(
    credential_id: str, body: CredentialValue, request: Request, who: Principal = Depends(principal)
):
    service = maestro(request).credentials
    return ok(
        request, service.replace_value(who, credential_id, body.value, body.expected_revision)
    )


@router.post("/credentials/{credential_id}/disable", response_model=Envelope[Credential])
def disable_credential(
    credential_id: str, body: StatusChange, request: Request, who: Principal = Depends(principal)
):
    service = maestro(request).credentials
    return ok(request, service.set_enabled(who, credential_id, False, body.expected_revision))


@router.post("/credentials/{credential_id}/enable", response_model=Envelope[Credential])
def enable_credential(
    credential_id: str, body: StatusChange, request: Request, who: Principal = Depends(principal)
):
    service = maestro(request).credentials
    return ok(request, service.set_enabled(who, credential_id, True, body.expected_revision))


@router.get("/master-key", response_model=Envelope[MasterKeyStatus])
def master_key(request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).credentials.master_status(who))


@router.post("/master-key/rotations", response_model=Envelope[MasterKeyStatus])
def rotate(body: MasterKeyRotation, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).credentials.rotate_master(who, body.expected_generation))


@router.get("/audit-events", response_model=Envelope[list[AuditEvent]])
def audit_events(
    request: Request,
    object_type: str | None = None,
    object_id: str | None = None,
    cursor: str | None = None,
    limit: int | None = None,
    who: Principal = Depends(principal),
):
    items, next_cursor = audit_queries.list_events(
        maestro(request).db,
        who,
        object_type=object_type,
        object_id=object_id,
        cursor=cursor,
        limit=limit,
    )
    return ok(request, items, next_cursor)
