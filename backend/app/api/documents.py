from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.schemas import (
    ConfirmRequest,
    DocumentDetail,
    DocumentSummary,
    ExportRequest,
    UpdateFieldsRequest,
    VerifyFieldRequest,
)
from app.services import documents as documents_service
from app.services import exports as exports_service
from app.services import imports as imports_service
from app.services import reviews as reviews_service

router = APIRouter(prefix="/documents", tags=["documents"])


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("", response_model=list[DocumentSummary])
def list_documents(session: Session = Depends(get_session)):
    return documents_service.list_summaries(session)


@router.post("", status_code=201, response_model=DocumentDetail)
def upload_document(
    file: UploadFile,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    return imports_service.import_document(file, session, settings)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, session: Session = Depends(get_session)):
    return documents_service.get_detail(session, document_id)


@router.get("/{document_id}/file", response_class=Response)
def get_document_file(
    document_id: str,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    content = documents_service.read_original(session, settings, document_id)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store", "Content-Disposition": 'inline; filename="document.pdf"'},
    )


@router.patch("/{document_id}/fields", response_model=DocumentDetail)
def update_fields(
    document_id: str, body: UpdateFieldsRequest, session: Session = Depends(get_session)
):
    return reviews_service.update_fields(document_id, body, session)


@router.post("/{document_id}/verify", response_model=DocumentDetail)
def verify_field(
    document_id: str, body: VerifyFieldRequest, session: Session = Depends(get_session)
):
    return reviews_service.set_field_verification(document_id, body, session)


@router.post("/{document_id}/confirm", response_model=DocumentDetail)
def confirm_document(
    document_id: str,
    body: ConfirmRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    return reviews_service.confirm_document(document_id, body.expected_version, session, settings)


@router.post("/{document_id}/exports", response_class=Response)
def export_document(
    document_id: str,
    body: ExportRequest,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    payload = exports_service.export_document(document_id, body.expected_version, session, settings)
    return Response(
        content=payload.body,
        media_type=payload.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{payload.filename}"',
            "Cache-Control": "no-store",
            "X-Export-SHA256": payload.sha256,
            "Access-Control-Expose-Headers": "Content-Disposition, X-Export-SHA256",
        },
    )
