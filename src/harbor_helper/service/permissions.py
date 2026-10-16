from harbor_helper.service.primitives import ServiceError


def admin(actor):
    if actor.get("access_credential_id") or actor["role"] != "admin":
        raise ServiceError("admin_required", "Administrator permission required", 403)


def cancel_allowed(actor, owner):
    if actor["role"] != "admin" and actor["id"] != owner:
        raise ServiceError("cancel_forbidden", "Members may cancel only their own tasks", 403)
