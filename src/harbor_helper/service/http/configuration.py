import uuid
from typing import Annotated

from fastapi import Depends

from harbor_helper.service.http.inputs import Account, Credential, MasterRotation, Rotation
from harbor_helper.service.primitives import ServiceError


def register(app, deps):
    administrator = deps.administrator
    dataset_administrator = deps.dataset_administrator

    @app.get("/api/v1/admin/master-key")
    def master_key_status(user: Annotated[dict, Depends(administrator)]):
        return deps.data.master_keys.status()

    @app.post("/api/v1/admin/master-key/rotate")
    def rotate_master_key(body: MasterRotation, user: Annotated[dict, Depends(administrator)]):
        deps.data.verify_password(user["username"], body.password.get_secret_value())
        return deps.data.master_keys.rotate(user, body.expected_generation)

    @app.get("/api/v1/admin/users")
    def users(user: Annotated[dict, Depends(administrator)]):
        return deps.data.users()

    @app.post("/api/v1/admin/users", status_code=201)
    def add_user(body: Account, user: Annotated[dict, Depends(administrator)]):
        result = deps.data.create_user(body.username, body.password.get_secret_value(), body.role)
        deps.data.event(user, "create_account", result["id"])
        return result

    @app.patch("/api/v1/admin/users/{user_id}")
    def update_user(user_id: str, body: dict, user: Annotated[dict, Depends(administrator)]):
        if set(body) - {"enabled", "password"} or (
            "enabled" in body and type(body["enabled"]) is not bool
        ):
            raise ServiceError("invalid_account", "Supported account updates: enabled, password")
        result = deps.data.update_user(user_id, **body)
        deps.data.event(user, "update_account", user_id)
        return result

    @app.get("/api/v1/admin/docker")
    def docker_discovery(user: Annotated[dict, Depends(administrator)]):
        from harbor_helper.service.docker import discover_docker

        return discover_docker()

    @app.post("/api/v1/admin/datasets/{object_id}/author-inputs/check")
    def inspect_author_inputs(
        object_id: str,
        user: Annotated[dict, Depends(dataset_administrator)],
        body: dict | None = None,
    ):
        if body is not None and set(body) - {"task_names", "version_id"}:
            raise ServiceError("author_task_selection", "Only task_names may be specified")
        return deps.application.configuration.inspect_author_parameters(
            object_id,
            task_names=body.get("task_names") if body and "task_names" in body else None,
            selection_supplied=bool(body is not None and "task_names" in body),
            version_id=body.get("version_id") if body else None,
        )

    @app.put("/api/v1/admin/datasets/{object_id}/author-inputs")
    def save_author_inputs(
        object_id: str, body: dict, user: Annotated[dict, Depends(dataset_administrator)]
    ):
        if "values" not in body or set(body) - {"values", "version_id"}:
            raise ServiceError("author_input_invalid", "Use only the discovered values object")
        return deps.application.configuration.save_author_parameters(
            object_id, body["values"], body.get("version_id")
        )

    @app.post("/api/v1/admin/catalog/{kind}")
    def save_catalog(kind: str, body: dict, user: Annotated[dict, Depends(dataset_administrator)]):
        if kind != "dataset":
            raise ServiceError("catalog_kind", "Unknown catalog kind", 404)
        with deps.store.control():
            result = deps.application.configuration.save(kind, body)
            deps.data.event(user, "save_" + kind, result["id"])
            return result

    @app.post("/api/v1/admin/catalog/{kind}/{object_id}/verify")
    def verify_catalog(
        kind: str, object_id: str, user: Annotated[dict, Depends(dataset_administrator)]
    ):
        if kind != "dataset":
            raise ServiceError("catalog_kind", "Unknown catalog kind", 404)
        try:
            selected = deps.application.configuration.ready_dataset(object_id)
        except ServiceError:
            raise ServiceError(
                "dataset_version_selection",
                "请在请求与目录管理中查询版本、预览并确认；手填引用不能导入新版本",
                409,
            ) from None
        result = deps.application.configuration.verify(
            kind, object_id, fixed_reference=selected["resolved"]
        )
        deps.data.event(user, "verify_" + kind, object_id)
        return result

    @app.patch("/api/v1/admin/settings")
    def settings(body: dict, user: Annotated[dict, Depends(administrator)]):
        with deps.store.control():
            return deps.application.configuration.save_settings(body)

    @app.post("/api/v1/admin/hub")
    def hub(body: Rotation, user: Annotated[dict, Depends(administrator)]):
        with deps.store.control():
            result = deps.application.configuration.save_hub(body.key.get_secret_value())
            deps.data.event(user, "rotate_hub", "team-source")
            return result

    @app.post("/api/v1/admin/hub/disable")
    def hub_disable(user: Annotated[dict, Depends(administrator)]):
        with deps.store.control():
            result = deps.application.configuration.save_hub(enabled=False)
            deps.data.event(user, "disable_hub", "team-source")
            return result

    @app.get("/api/v1/admin/providers")
    def providers(user: Annotated[dict, Depends(administrator)]):
        return deps.data.objects("provider")

    @app.post("/api/v1/admin/providers")
    def provider(body: dict, user: Annotated[dict, Depends(administrator)]):
        with deps.application.store.control():
            result = deps.data.models.save_object("provider", body)
            deps.data.event(user, "save_provider", result["id"])
            return result

    @app.get("/api/v1/admin/model-profiles")
    def profiles(user: Annotated[dict, Depends(administrator)]):
        return deps.data.objects("profile")

    @app.post("/api/v1/admin/model-profiles")
    def profile(body: dict, user: Annotated[dict, Depends(administrator)]):
        with deps.application.store.control():
            result = deps.data.models.save_object("profile", body)
            deps.data.event(user, "save_model_profile", result["id"])
            return result

    @app.get("/api/v1/admin/credentials")
    def credentials(user: Annotated[dict, Depends(administrator)]):
        return deps.data.credentials()

    @app.post("/api/v1/admin/credentials", status_code=201)
    def credential(body: Credential, user: Annotated[dict, Depends(administrator)]):
        with deps.application.store.control():
            result = deps.data.add_credential(
                body.id or uuid.uuid4().hex,
                body.provider_id,
                body.label,
                body.key.get_secret_value(),
            )
            deps.data.event(user, "add_credential", result["id"])
            return result

    @app.post("/api/v1/admin/credentials/{credential_id}/rotate")
    def rotate(credential_id: str, body: Rotation, user: Annotated[dict, Depends(administrator)]):
        with deps.application.store.control():
            old = deps.data.credential(credential_id)
            result = deps.data.add_credential(
                credential_id,
                old["provider_id"],
                old["label"],
                body.key.get_secret_value(),
                rotate=True,
            )
            deps.data.event(user, "rotate_credential", credential_id)
        deps.data.prune_credentials()
        return result

    @app.post("/api/v1/admin/credentials/{credential_id}/disable")
    def disable(credential_id: str, user: Annotated[dict, Depends(administrator)]):
        with deps.application.store.control():
            result = deps.data.disable_credential(credential_id)
            deps.data.event(user, "disable_credential", credential_id)
            return result

    @app.get("/api/v1/admin/limits")
    def limits(user: Annotated[dict, Depends(administrator)]):
        return deps.data.limits()

    @app.patch("/api/v1/admin/limits")
    def set_limits(body: dict, user: Annotated[dict, Depends(administrator)]):
        with deps.application.store.control():
            result = deps.data.set_limits(body)
            deps.data.event(user, "set_limits", "global")
            return result
