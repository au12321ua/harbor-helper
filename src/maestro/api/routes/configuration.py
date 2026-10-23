"""Model configurations, harness versions, the team policy and configuration resolution.

Reading is open to every signed-in principal; changing is for administrators in a web
session. Resolution is the step before submission that web and SDK share (03).
"""

from fastapi import APIRouter, Depends, Request

from maestro.api.deps import maestro, ok, principal
from maestro.api.models import (
    ConfigRequest,
    ConfigResolution,
    CredentialName,
    EnabledChange,
    Envelope,
    Harness,
    HarnessAdapter,
    HarnessCreate,
    ModelConfig,
    ModelConfigCreate,
    ModelConfigRevise,
    RecycleEntry,
    TeamPolicy,
    TeamPolicyRevision,
    TeamPolicyUpdate,
)
from maestro.services.principal import Principal, require_admin_session

router = APIRouter(prefix="/api/v1", tags=["configuration"])


# --- reading ----------------------------------------------------------------------------


@router.get("/model-configs", response_model=Envelope[list[ModelConfig]])
def model_configs(
    request: Request, include_disabled: bool = False, who: Principal = Depends(principal)
):
    return ok(request, maestro(request).models.list_models(who, include_disabled))


@router.get("/model-configs/{config_id}", response_model=Envelope[ModelConfig])
def model_config(config_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).models.get_model(who, config_id))


@router.get("/harness-versions", response_model=Envelope[list[Harness]])
def harnesses(request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).models.list_harnesses(who))


@router.get("/harness-versions/{harness_id}", response_model=Envelope[Harness])
def harness(harness_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).models.get_harness(who, harness_id))


@router.get("/credentials", response_model=Envelope[list[CredentialName]])
def credential_names(request: Request, who: Principal = Depends(principal)):
    """Enabled team credentials by name, to reference secret parameters; no values."""
    return ok(request, maestro(request).credentials.directory(who))


@router.get("/team-policy", response_model=Envelope[TeamPolicy])
def team_policy(request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).policies.get(who))


# --- resolution ---------------------------------------------------------------------


@router.post("/config-resolutions", response_model=Envelope[ConfigResolution], status_code=201)
def resolve(body: ConfigRequest, request: Request, who: Principal = Depends(principal)):
    """Effective configuration, where each value came from, and what blocks it. Valid
    for a few minutes; submit it with ``resolution_id``. Reserves nothing."""
    # Unset fields stay absent: an experiment plan may fill them in.
    return ok(request, maestro(request).runs.resolve(who, body.model_dump(exclude_unset=True)))


@router.get("/config-resolutions/{resolution_id}", response_model=Envelope[ConfigResolution])
def resolution(resolution_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).runs.get_resolution(who, resolution_id))


# --- administration ---------------------------------------------------------------------


@router.get(
    "/admin/harness-adapters", response_model=Envelope[list[HarnessAdapter]], tags=["admin"]
)
def adapters(request: Request, who: Principal = Depends(principal)):
    require_admin_session(who)
    return ok(request, maestro(request).models.public_adapters())


@router.post(
    "/admin/model-configs", response_model=Envelope[ModelConfig], status_code=201, tags=["admin"]
)
def create_model(body: ModelConfigCreate, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).models.create_model(who, body.model_dump()))


@router.put(
    "/admin/model-configs/{config_id}", response_model=Envelope[ModelConfig], tags=["admin"]
)
def revise_model(
    config_id: str, body: ModelConfigRevise, request: Request, who: Principal = Depends(principal)
):
    """A new revision; runs already accepted keep the revision they used."""
    fields = body.model_dump()
    expected = fields.pop("expected_revision")
    return ok(request, maestro(request).models.revise_model(who, config_id, fields, expected))


@router.post(
    "/admin/model-configs/{config_id}/enabled", response_model=Envelope[ModelConfig], tags=["admin"]
)
def model_enabled(
    config_id: str, body: EnabledChange, request: Request, who: Principal = Depends(principal)
):
    return ok(request, maestro(request).models.set_model_enabled(who, config_id, body.enabled))


@router.delete(
    "/admin/model-configs/{config_id}", response_model=Envelope[RecycleEntry], tags=["admin"]
)
def delete_model(config_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).recycle.delete(who, "model_config", config_id))


@router.post(
    "/admin/harness-versions", response_model=Envelope[Harness], status_code=201, tags=["admin"]
)
def create_harness(body: HarnessCreate, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).models.create_harness(who, body.model_dump()))


@router.post(
    "/admin/harness-versions/{harness_id}/enabled", response_model=Envelope[Harness], tags=["admin"]
)
def harness_enabled(
    harness_id: str, body: EnabledChange, request: Request, who: Principal = Depends(principal)
):
    return ok(request, maestro(request).models.set_harness_enabled(who, harness_id, body.enabled))


@router.delete(
    "/admin/harness-versions/{harness_id}", response_model=Envelope[RecycleEntry], tags=["admin"]
)
def delete_harness(harness_id: str, request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).recycle.delete(who, "harness_version", harness_id))


@router.get(
    "/admin/team-policy/revisions",
    response_model=Envelope[list[TeamPolicyRevision]],
    tags=["admin"],
)
def policy_history(request: Request, who: Principal = Depends(principal)):
    return ok(request, maestro(request).policies.history(who))


@router.put("/admin/team-policy", response_model=Envelope[TeamPolicy], tags=["admin"])
def update_policy(body: TeamPolicyUpdate, request: Request, who: Principal = Depends(principal)):
    """Change some settings; a new revision takes effect for new work at once."""
    return ok(
        request,
        maestro(request).policies.update(who, body.values, body.expected_revision),
    )
