from harbor_helper.service.primitives import ServiceError


def admin(actor):
    if actor.get("access_credential_id") or actor["role"] != "admin":
        raise ServiceError("admin_required", "Administrator permission required", 403)


def cancel_allowed(actor, owner):
    if actor["role"] != "admin" and actor["id"] != owner:
        raise ServiceError("cancel_forbidden", "Members may cancel only their own tasks", 403)


def management_admin(actor, scope):
    role = actor.get("account_role", actor["role"])
    if role != "admin" or (actor.get("access_credential_id") and scope not in actor["scopes"]):
        raise ServiceError("management_forbidden", "管理员身份与对应管理权限同时必需", 403)
