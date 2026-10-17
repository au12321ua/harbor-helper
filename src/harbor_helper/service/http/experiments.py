import json
from typing import Annotated

from fastapi import Depends, Header, Request, Response
from fastapi.responses import FileResponse

from harbor_helper.service import dtos, machine
from harbor_helper.service.browser_contracts import Materials
from harbor_helper.service.dtos import RetryInput, SubmissionInput
from harbor_helper.service.http.dependencies import token
from harbor_helper.service.primitives import ServiceError
from harbor_helper.service.views import public_submission, safe_view


def register(app, deps):
    actor = deps.actor
    administrator = deps.administrator

    @app.get("/api/v1/catalog")
    def catalog(user: Annotated[dict, Depends(actor)]):
        return (
            machine.discovery(deps.application, user)
            if user.get("access_credential_id")
            else deps.application.catalog(user["id"])
        )

    @app.get("/api/v1/usage")
    def usage(user: Annotated[dict, Depends(actor)]):
        return deps.application.usage()

    @app.get("/api/v1/runs")
    def runs(user: Annotated[dict, Depends(actor)]):
        return deps.application.runs()

    @app.post(
        "/api/v1/submissions",
        status_code=202,
        response_model=dtos.Accepted,
        response_model_exclude_unset=True,
    )
    def submit(
        request: Request,
        body: SubmissionInput,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
    ):
        return machine.accepted_view(
            user,
            deps.application.accept(
                user,
                body.model_dump(exclude_unset=True),
                idempotency_key,
                access_value=token(request),
            ),
        )

    @app.get("/api/v1/submissions/{submission_id}")
    def submission(submission_id: str, user: Annotated[dict, Depends(actor)]):
        return machine.accepted_view(user, public_submission(deps.data.submission(submission_id)))

    @app.post(
        "/api/v1/submissions/{submission_id}/retry",
        status_code=202,
        response_model=dtos.Accepted,
        response_model_exclude_unset=True,
    )
    def recover_submission(
        request: Request,
        submission_id: str,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
        body: dtos.EmptyInput | None = None,
    ):
        return machine.accepted_view(
            user,
            deps.application.recover_submission(
                user, submission_id, idempotency_key, access_value=token(request)
            ),
        )

    @app.post(
        "/api/v1/submissions/{submission_id}/cancel",
        response_model=dtos.Accepted,
        response_model_exclude_unset=True,
    )
    def cancel_submission(
        submission_id: str,
        user: Annotated[dict, Depends(actor)],
        body: dtos.EmptyInput | None = None,
    ):
        return machine.accepted_view(user, deps.application.cancel_submission(user, submission_id))

    @app.get("/api/v1/runs/{run_id}")
    def run(run_id: str, user: Annotated[dict, Depends(actor)]):
        return deps.application.detail(run_id)

    @app.get("/api/v1/runs/{run_id}/report/download")
    def download_report(run_id: str, user: Annotated[dict, Depends(actor)]):
        report = deps.application.safe_report(run_id)
        if report is None:
            raise ServiceError("report_pending", "Report not available", 409)
        # run identifier is generated and resolved by Store; never an arbitrary filename.
        return Response(
            json.dumps(report, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{run_id}-report.json"'},
        )

    @app.get("/api/v1/runs/{run_id}/logs")
    def logs(run_id: str, user: Annotated[dict, Depends(actor)]):
        return deps.application.logs(run_id)

    @app.get("/api/v1/runs/{run_id}/report")
    def report(run_id: str, user: Annotated[dict, Depends(actor)]):
        value = deps.application.safe_report(run_id)
        return value

    @app.post("/api/v1/runs/{run_id}/cancel", response_model=dtos.CancelResult)
    def cancel(
        run_id: str, user: Annotated[dict, Depends(actor)], body: dtos.EmptyInput | None = None
    ):
        return deps.application.cancel_run(user, run_id)

    @app.post(
        "/api/v1/runs/{run_id}/rerun",
        status_code=202,
        response_model=dtos.Accepted,
        response_model_exclude_unset=True,
    )
    def rerun(
        request: Request,
        run_id: str,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
        body: dtos.EmptyInput | None = None,
    ):
        return machine.accepted_view(
            user,
            deps.application.accept(
                user, {}, idempotency_key, parent=run_id, access_value=token(request)
            ),
        )

    @app.post(
        "/api/v1/runs/{run_id}/retry",
        status_code=202,
        response_model=dtos.Accepted,
        response_model_exclude_unset=True,
    )
    def retry_run(
        request: Request,
        run_id: str,
        body: RetryInput,
        user: Annotated[dict, Depends(actor)],
        idempotency_key: str | None = Header(default=None),
    ):
        return machine.accepted_view(
            user,
            deps.application.accept(
                user,
                body.model_dump(exclude_unset=True),
                idempotency_key,
                parent=run_id,
                retry=True,
                access_value=token(request),
            ),
        )

    @app.post("/api/v1/compare")
    def compare(body: dtos.CompareInput, user: Annotated[dict, Depends(actor)]):
        from harbor_helper.results.reports import compare

        body = body.model_dump()
        reports = tuple(deps.application.safe_report(body[k]) for k in ("left", "right"))
        if any(r is None for r in reports):
            raise ServiceError("report_pending", "Both published reports are required", 409)
        value = safe_view(
            compare(deps.application.store, body["left"], body["right"], published_reports=reports)
        )
        return value

    @app.post("/api/v1/machine/compare", response_model=dtos.Comparison)
    def machine_compare(body: dtos.CompareInput, user: Annotated[dict, Depends(actor)]):
        value = compare(body, user)
        value.pop("environment_observations", None)
        value["config_changes"] = {k: {"changed": True} for k in value["config_changes"]}
        return value

    @app.get("/api/v1/runs/{run_id}/artifacts/{file_id}")
    def artifact(run_id: str, file_id: str, user: Annotated[dict, Depends(actor)]):
        path = deps.application.artifact_path(run_id, file_id)
        return FileResponse(
            path,
            media_type="application/octet-stream",
            filename=path.name,
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{__import__('urllib.parse', fromlist=['quote']).quote(path.name)}"
            },
        )

    @app.delete("/api/v1/runs/{run_id}/artifacts/{file_id}")
    def delete_artifact(run_id: str, file_id: str, user: Annotated[dict, Depends(administrator)]):
        return deps.application.delete_artifact(user, run_id, file_id)

    @app.get(
        "/api/v1/runs/{run_id}/evidence",
        response_model=Materials,
        response_model_exclude_unset=True,
    )
    def evidence_manifest(run_id: str, user: Annotated[dict, Depends(actor)]):
        from harbor_helper.service.materials import manifest

        return manifest(deps.application, user, run_id)

    def evidence_response(run_id, user, file_id=None):
        from fastapi.responses import StreamingResponse
        from starlette.background import BackgroundTask

        from harbor_helper.service.materials import snapshot

        stream, size, sha = snapshot(deps.application, user, run_id, file_id)

        def chunks():
            try:
                while chunk := stream.read(65536):
                    yield chunk
            finally:
                stream.close()

        return StreamingResponse(
            chunks(),
            media_type="application/octet-stream",
            headers={
                "Content-Length": str(size),
                "X-Content-SHA256": sha,
                "Content-Disposition": 'attachment; filename="evidence.'
                + ("bin" if file_id else "zip")
                + '"',
            },
            background=BackgroundTask(stream.close),
        )

    @app.get("/api/v1/runs/{run_id}/evidence/package")
    def evidence_package(run_id: str, user: Annotated[dict, Depends(actor)]):
        return evidence_response(run_id, user)

    @app.get("/api/v1/runs/{run_id}/evidence/files/{file_id}")
    def evidence_file(run_id: str, file_id: str, user: Annotated[dict, Depends(actor)]):
        return evidence_response(run_id, user, file_id)
