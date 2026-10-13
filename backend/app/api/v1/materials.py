"""文件说明：配套资料受控API；统一身份、管理写入CSRF及附件读取权限。"""
import hashlib
import io
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from openpyxl import Workbook
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.api.dependencies import require_permission
from app.application.material_service import MaterialService, MaterialError, HEADERS, describe_errors, fingerprint
from app.config import get_settings
from app.infrastructure.db.session import get_db_session
from app.schemas.materials import ImageFields, SaveMaterial, BatchAction

router = APIRouter(prefix="/materials", tags=["materials"])
read = require_permission("material.read")
write = require_permission("material.manage", csrf=True)


@contextmanager
def operation(session, principal, request, mutate=False):
    try:
        yield MaterialService(session, principal, getattr(request.state, "request_id", "materials"))
        if mutate:
            session.commit()
    except MaterialError as exc:
        session.rollback()
        raise HTTPException(exc.status, str(exc)) from exc
    except (IntegrityError, StaleDataError) as exc:
        session.rollback()
        raise HTTPException(409, "资料已经存在或已被修改，请刷新后重试") from exc
    except ValidationError as exc:
        session.rollback()
        # 字段约束按400返回中文提示，与接口文档“400字段/发布约束”一致。
        raise HTTPException(400, "资料字段不合法：" + describe_errors(exc)) from exc


@router.get("")
def listing(request: Request, q: str = Query("", max_length=200), kind: Literal["", "CASE", "IMAGE"] = "",
            state: Literal["", "DRAFT", "PUBLISHED", "OFFLINE"] = "PUBLISHED", domain: str = Query("", max_length=100),
            sort: Literal["updated", "published", "relevance"] = "updated", page: int = Query(1, ge=1),
            principal=Depends(read), session: Session = Depends(get_db_session)):
    with operation(session, principal, request) as service:
        return service.listing(q=q, kind=kind, state=state, domain=domain, sort=sort, page=page)


@router.get("/case-template")
def template(_principal=Depends(read)):
    book = Workbook()
    sheet = book.active
    sheet.title = "案例"
    sheet.append(HEADERS)
    sheet.freeze_panes = "A2"
    for col in "ABCDEFGHIJ":
        sheet.column_dimensions[col].width = 30 if col < "E" else 60
    stream = io.BytesIO()
    book.save(stream)
    return Response(stream.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="case-import-template.xlsx"'})


@router.get("/recommendations")
def recommendations(request: Request, q: str = Query("", max_length=2000),
                    kind: Literal["CASE", "IMAGE"] | None = None,
                    principal=Depends(read), session: Session = Depends(get_db_session)):
    with operation(session, principal, request) as service:
        return service.recommend(q, kind=kind)


@router.post("/imports/preview")
def preview(request: Request, file: UploadFile = File(...),
            principal=Depends(write), session: Session = Depends(get_db_session)):
    with operation(session, principal, request, True) as service:
        if not (file.filename or "").lower().endswith(".xlsx"):
            raise MaterialError("仅接受.xlsx文件")
        return service.preview(file.file.read(10 * 1024 * 1024 + 1), Path(file.filename.replace("\\", "/")).name[:255])


@router.post("/imports/{batch_id}/confirm")
def confirm(batch_id: str, request: Request, principal=Depends(write), session: Session = Depends(get_db_session)):
    with operation(session, principal, request, True) as service:
        return service.confirm(batch_id)


@router.post("/images", status_code=201)
def upload_image(request: Request, file: UploadFile = File(...), metadata: str = Form("{}"),
                 principal=Depends(write), session: Session = Depends(get_db_session)):
    stored = None
    try:
        with operation(session, principal, request, True) as service:
            raw = file.file.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                raise MaterialError("图片最多10MB")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter(
                        "error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(raw)) as image:
                        fmt, dimensions = image.format, image.size
                        if fmt not in {"PNG", "JPEG"} or dimensions[0] * dimensions[1] > 25_000_000 or getattr(image, "n_frames", 1) > 1:
                            raise MaterialError("仅支持静态PNG/JPEG，最多2500万像素")
                        image.verify()
            except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise MaterialError("图片损坏或像素尺寸过大") from exc
            filename = Path(
                (file.filename or "流程图.png").replace("\\", "/")).name[:255]
            fields = ImageFields.model_validate_json(metadata).model_dump()
            ext, mime = (
                ".png", "image/png") if fmt == "PNG" else (".jpg", "image/jpeg")
            key = uuid4().hex + ext
            item = service.create("IMAGE", fields, fingerprint("IMAGE", raw), file={"key": key, "filename": filename,
                                                                                    "sha256": hashlib.sha256(raw).hexdigest(), "mime": mime, "width": dimensions[0], "height": dimensions[1], "size": len(raw)})
            root = get_settings().materials_root.resolve()
            root.mkdir(parents=True, exist_ok=True)
            stored = root / key
            with stored.open("xb") as stream:
                stream.write(raw)
            result = service.detail(item.id)
        return result
    except Exception:
        # 仅清理本次新建且尚未成功提交的UUID文件，绝不触碰原始上传文件。
        if stored and stored.exists():
            stored.unlink()
        raise


@router.post("/actions")
def actions(body: BatchAction, request: Request, principal=Depends(write), session: Session = Depends(get_db_session)):
    with operation(session, principal, request, True) as service:
        return service.action(body)


@router.get("/{material_id}")
def detail(material_id: str, request: Request, revision_id: str | None = None,
           principal=Depends(read), session: Session = Depends(get_db_session)):
    with operation(session, principal, request) as service:
        return service.detail(material_id, revision_id)


@router.put("/{material_id}")
def save(material_id: str, body: SaveMaterial, request: Request, principal=Depends(write), session: Session = Depends(get_db_session)):
    with operation(session, principal, request, True) as service:
        return service.save(material_id, body)


@router.get("/{material_id}/revisions/{revision_id}/file")
def image_file(material_id: str, revision_id: str, request: Request,
               principal=Depends(read), session: Session = Depends(get_db_session)):
    with operation(session, principal, request) as service:
        item = service.get(material_id)
        rev = service.revision(item, revision_id)
        import json
        file = json.loads(rev.payload_json).get("file")
        if not file:
            raise MaterialError("该资料没有图片", 404)
        root = get_settings().materials_root.resolve()
        path = (root / file["key"]).resolve()
        if path.parent != root or not path.is_file():
            raise MaterialError("图片文件不可用", 404)
        return FileResponse(path, media_type=file["mime"], headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
