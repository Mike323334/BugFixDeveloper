from __future__ import annotations

import json
import os
import secrets
import time
import uuid
import boto3

from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)

from botocore.config import Config
from botocore.exceptions import ClientError

from fastapi.responses import (
    FileResponse,
    JSONResponse,
    Response,
)

from fastapi.staticfiles import StaticFiles

from fastapi.staticfiles import StaticFiles

from itsdangerous import URLSafeTimedSerializer

from .database import (
    USE_POSTGRES,
    database_status,
    get_db,
    init_db,
    placeholder,
)


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent

load_dotenv(ROOT / ".env")

DATA_DIR = Path(
    os.getenv("DATA_DIR", str(ROOT / "data"))
).resolve()

UPLOAD_DIR = DATA_DIR / "uploads"

STATIC_DIR = ROOT.parent / "frontend" / "static"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# NEON OBJECT STORAGE
# ============================================================

NEON_STORAGE_BUCKET = os.getenv(
    "NEON_STORAGE_BUCKET",
    "",
).strip()

AWS_ENDPOINT_URL_S3 = os.getenv(
    "AWS_ENDPOINT_URL_S3",
    "",
).strip()

AWS_REGION = os.getenv(
    "AWS_REGION",
    "",
).strip()

storage_client = None

storage_configuration = {
    "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID", ""),
    "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY", ""),
    "AWS_ENDPOINT_URL_S3": AWS_ENDPOINT_URL_S3,
    "AWS_REGION": AWS_REGION,
    "NEON_STORAGE_BUCKET": NEON_STORAGE_BUCKET,
}

if all(value.strip() for value in storage_configuration.values()):

    storage_client = boto3.client(
        "s3",
        endpoint_url=AWS_ENDPOINT_URL_S3,
        region_name=AWS_REGION,
        aws_access_key_id=storage_configuration[
            "AWS_ACCESS_KEY_ID"
        ],
        aws_secret_access_key=storage_configuration[
            "AWS_SECRET_ACCESS_KEY"
        ],
        config=Config(
            s3={
                "addressing_style": "path",
            },
            retries={
                "max_attempts": 3,
                "mode": "standard",
            },
        ),
    )
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")

ADMIN_PASSWORD = os.getenv(
    "ADMIN_PASSWORD",
    "change-this-password",
)

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "dev-only-change-this-secret-key",
)

COOKIE_SECURE = (
    os.getenv("COOKIE_SECURE", "false").lower()
    in {"1", "true", "yes"}
)

COOKIE_NAME = "bugfix_admin_session"

SESSION_MAX_AGE = 60 * 60 * 12

MAX_IMAGE_BYTES = 5 * 1024 * 1024

MAX_IMAGES_PER_CASE = 6

ALLOWED_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
}

SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
    ".gif": (b"GIF87a", b"GIF89a"),
}

serializer = URLSafeTimedSerializer(
    SECRET_KEY,
    salt="bugfix-admin-session",
)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="BugFix Developer API",
    version="1.1.0",
)

app.mount(
    "/static",
    StaticFiles(directory=STATIC_DIR),
    name="static",
)




# ============================================================
# DATABASE INITIALIZATION
# ============================================================

@app.on_event("startup")
def startup_event() -> None:
    init_db()


# ============================================================
# ADMIN AUTHENTICATION
# ============================================================

def is_admin(request: Request) -> bool:

    token = request.cookies.get(COOKIE_NAME)

    if not token:
        return False

    try:
        payload = serializer.loads(
            token,
            max_age=SESSION_MAX_AGE,
        )

    except Exception:
        return False

    return (
        payload.get("admin") is True
        and payload.get("username") == ADMIN_USERNAME
    )


def require_admin(request: Request) -> None:

    if not is_admin(request):

        raise HTTPException(
            status_code=401,
            detail="Please sign in to manage case studies.",
        )


# ============================================================
# IMAGE NORMALIZATION
# ============================================================

def normalize_images(
    raw: str | list[Any] | None,
) -> list[dict[str, str]]:
    """
    Supports legacy image strings and the current format:

    [
        {
            "path": "/uploads/example.png",
            "comment": "Description of the screenshot"
        }
    ]
    """

    try:

        if isinstance(raw, (str, type(None))):
            items = json.loads(raw or "[]")

        else:
            items = raw

    except (ValueError, TypeError):
        items = []

    normalized: list[dict[str, str]] = []

    if not isinstance(items, list):
        return normalized

    for item in items[:MAX_IMAGES_PER_CASE]:

        if isinstance(item, str):

            path = item
            comment = ""

        elif isinstance(item, dict):

            path = item.get("path", "")
            comment = item.get("comment", "")

        else:
            continue

        if (
            isinstance(path, str)
            and path.startswith("/uploads/")
            and Path(path).name
        ):

            normalized.append(
                {
                    "path": path,
                    "comment": str(comment or "")[:1000],
                }
            )

    return normalized


def image_paths(
    images: list[dict[str, str]],
) -> list[str]:

    return [
        item["path"]
        for item in images
    ]


# ============================================================
# DATABASE ROW CONVERSION
# ============================================================

def case_to_dict(row: Any) -> dict[str, Any]:

    if row is None:
        raise ValueError("Cannot convert an empty database row.")

    return {
        "id": row["id"],
        "title": row["title"],
        "url": row["url"],
        "technology": row["technology"],
        "summary": row["summary"],
        "problem": row["problem"],
        "diagnosis": row["diagnosis"],
        "solution": row["solution"],
        "result": row["result"],
        "images": normalize_images(row["image_paths"]),
        "published": bool(row["published"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ============================================================
# IMAGE UPLOAD
# ============================================================

# ============================================================
# IMAGE STORAGE HELPERS
# ============================================================

def require_storage_client():
    """
    Return the configured Neon Object Storage client.

    Fail explicitly instead of silently saving new images locally.
    """

    if storage_client is None:

        raise HTTPException(
            status_code=503,
            detail="Neon Object Storage is not configured.",
        )

    return storage_client


def storage_key_from_path(path: str) -> str | None:
    """
    Convert /uploads/example.png into example.png.

    Only accept simple filenames, preventing arbitrary object keys.
    """

    if not isinstance(path, str):
        return None

    if not path.startswith("/uploads/"):
        return None

    filename = path.removeprefix("/uploads/")

    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
    ):
        return None

    return filename


def image_content_type(filename: str) -> str:
    """
    Return the content type for supported image extensions.
    """

    ext = Path(filename).suffix.lower()

    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")


async def save_image(upload: UploadFile) -> str:
    """
    Validate and upload an image to Neon Object Storage.

    Return the existing URL format so the frontend does not
    need to change.
    """

    client = require_storage_client()

    original_name = upload.filename or "image"

    ext = Path(original_name).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:

        raise HTTPException(
            status_code=400,
            detail="Use PNG, JPG, WEBP, or GIF images only.",
        )

    data = await upload.read(MAX_IMAGE_BYTES + 1)

    if not data:

        raise HTTPException(
            status_code=400,
            detail="The uploaded image is empty.",
        )

    if len(data) > MAX_IMAGE_BYTES:

        raise HTTPException(
            status_code=413,
            detail="Each image must be 5 MB or smaller.",
        )

    valid = any(
        data.startswith(signature)
        for signature in SIGNATURES[ext]
    )

    if ext == ".webp":

        valid = (
            len(data) >= 12
            and data.startswith(b"RIFF")
            and data[8:12] == b"WEBP"
        )

    if not valid:

        raise HTTPException(
            status_code=400,
            detail="The file content does not match its image extension.",
        )

    filename = f"{uuid.uuid4().hex}{ext}"

    try:

        client.put_object(
            Bucket=NEON_STORAGE_BUCKET,
            Key=filename,
            Body=data,
            ContentType=image_content_type(filename),
        )

    except Exception as exc:

        print(
            f"Neon image upload failed: {type(exc).__name__}"
        )

        raise HTTPException(
            status_code=502,
            detail="The image could not be uploaded to object storage.",
        ) from exc

    return f"/uploads/{filename}"


# ============================================================
# IMAGE RETRIEVAL
# ============================================================

@app.get("/uploads/{filename}")
def get_uploaded_image(filename: str):

    # Reject path traversal and unexpected filenames.
    if (
        not filename
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid image filename.",
        )

    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:

        raise HTTPException(
            status_code=404,
            detail="Image not found.",
        )

    # Try Neon Object Storage first.
    if storage_client is not None:

        try:

            result = storage_client.get_object(
                Bucket=NEON_STORAGE_BUCKET,
                Key=filename,
            )

            image_data = result["Body"].read()

            content_type = result.get(
                "ContentType",
                image_content_type(filename),
            )

            return Response(
                content=image_data,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=3600",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        except ClientError as exc:

            error_code = str(
                exc.response.get("Error", {}).get("Code", "")
            )

            # Only fall back to local storage when the object
            # is missing. Permission and service errors must
            # not be mistaken for missing images.
            if error_code not in {
                "NoSuchKey",
                "404",
                "NotFound",
            }:

                print(
                    "Neon image retrieval failed: "
                    f"{error_code}"
                )

                raise HTTPException(
                    status_code=502,
                    detail="Unable to retrieve the image from storage.",
                ) from exc

    # Backward compatibility for images not migrated yet.
    local_path = (UPLOAD_DIR / filename).resolve()

    if (
        local_path.parent == UPLOAD_DIR.resolve()
        and local_path.is_file()
    ):

        return FileResponse(
            local_path,
            media_type=image_content_type(filename),
            headers={
                "X-Content-Type-Options": "nosniff",
            },
        )

    raise HTTPException(
        status_code=404,
        detail="Image not found.",
    )


# ============================================================
# DELETE UNUSED IMAGES
# ============================================================

def delete_unused_uploads(
    paths: list[str],
) -> None:
    """
    Delete images only when no remaining case study references them.

    Supports both Neon Object Storage and legacy local images.
    Cleanup failures do not invalidate a committed database change.
    """

    if not paths:
        return

    try:

        with get_db() as connection:

            rows = connection.execute(
                "SELECT image_paths FROM cases"
            ).fetchall()

            referenced_paths = set()

            for row in rows:

                referenced_paths.update(
                    image_paths(
                        normalize_images(row["image_paths"])
                    )
                )

    except Exception as exc:

        # If we cannot establish whether an image is still in use,
        # do not delete it.
        print(
            "Image cleanup skipped because database references "
            f"could not be checked: {type(exc).__name__}"
        )

        return

    client = storage_client

    for path in set(paths):

        if not isinstance(path, str):
            continue

        # Never delete images that another case study still uses.
        if path in referenced_paths:
            continue

        filename = storage_key_from_path(path)

        if not filename:
            continue

        # Remove the remote object.
        if client is not None:

            try:

                client.delete_object(
                    Bucket=NEON_STORAGE_BUCKET,
                    Key=filename,
                )

            except Exception as exc:

                print(
                    "Neon image cleanup failed: "
                    f"{type(exc).__name__}"
                )

        # Remove any legacy local copy as well.
        local_path = (UPLOAD_DIR / filename).resolve()

        if (
            local_path.parent == UPLOAD_DIR.resolve()
            and local_path.is_file()
        ):

            try:

                local_path.unlink()

            except OSError:

                pass

# ============================================================
# FRONTEND PAGES
# ============================================================

@app.get("/")
def home():

    index_file = STATIC_DIR / "index.html"

    if not index_file.is_file():

        raise HTTPException(
            status_code=404,
            detail="Frontend index.html was not found.",
        )

    return FileResponse(index_file)


@app.get("/admin")
def admin_page():

    admin_file = STATIC_DIR / "admin.html"

    if not admin_file.is_file():

        raise HTTPException(
            status_code=404,
            detail="Frontend admin.html was not found.",
        )

    return FileResponse(admin_file)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/api/health")
def health():

    return {
        "status": "ok",
        "database": "postgresql" if USE_POSTGRES else "sqlite",
    }


@app.get("/api/health/database")
def health_database():

    try:

        status = database_status()

        return {
            "status": "ok",
            **status,
        }

    except Exception as exc:

        # Keep technical details out of public responses.
        print(f"Database health check failed: {exc}")

        raise HTTPException(
            status_code=503,
            detail="Database connection failed.",
        )


# ============================================================
# AUTHENTICATION: CURRENT ADMIN
# ============================================================

@app.get("/api/auth/me")
def auth_me(request: Request):

    if not is_admin(request):

        return {
            "authenticated": False,
        }

    return {
        "authenticated": True,
        "username": ADMIN_USERNAME,
    }


# ============================================================
# AUTHENTICATION: LOGIN
# ============================================================

@app.post("/api/auth/login")
async def auth_login(request: Request):

    try:
        body = await request.json()

    except Exception:

        raise HTTPException(
            status_code=400,
            detail="Invalid JSON request.",
        )

    username = str(body.get("username", ""))
    password = str(body.get("password", ""))

    username_valid = secrets.compare_digest(
        username,
        ADMIN_USERNAME,
    )

    password_valid = secrets.compare_digest(
        password,
        ADMIN_PASSWORD,
    )

    if not (username_valid and password_valid):

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password.",
        )

    token = serializer.dumps(
        {
            "admin": True,
            "username": ADMIN_USERNAME,
        }
    )

    response = JSONResponse(
        {
            "authenticated": True,
            "username": ADMIN_USERNAME,
        }
    )

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
        path="/",
    )

    return response


# ============================================================
# AUTHENTICATION: LOGOUT
# ============================================================

@app.post("/api/auth/logout")
def auth_logout():

    response = JSONResponse(
        {
            "authenticated": False,
        }
    )

    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )

    return response


# ============================================================
# LIST CASE STUDIES
# ============================================================

@app.get("/api/cases")
def list_cases(request: Request):

    admin = is_admin(request)

    with get_db() as connection:

        if admin:

            rows = connection.execute(
                """
                SELECT *
                FROM cases
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()

        else:

            rows = connection.execute(
                """
                SELECT *
                FROM cases
                WHERE published = 1
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()

    return [
        case_to_dict(row)
        for row in rows
    ]


# ============================================================
# UPLOAD IMAGES
# ============================================================

@app.post("/api/uploads")
async def upload_images(
    request: Request,
    files: list[UploadFile] = File(...),
):

    require_admin(request)

    if not files:

        raise HTTPException(
            status_code=400,
            detail="Select at least one image.",
        )

    if len(files) > MAX_IMAGES_PER_CASE:

        raise HTTPException(
            status_code=400,
            detail=f"You can upload at most {MAX_IMAGES_PER_CASE} images.",
        )

    saved_paths: list[str] = []

    try:

        for upload in files:

            saved_path = await save_image(upload)

            saved_paths.append(saved_path)

    except Exception:

        delete_unused_uploads(saved_paths)

        raise

    return {
        "images": [
            {
                "path": path,
                "comment": "",
            }
            for path in saved_paths
        ]
    }


# ============================================================
# CREATE CASE STUDY
# ============================================================

@app.post("/api/cases")
def create_case(
    request: Request,
    title: str = Form(...),
    url: str = Form(""),
    technology: str = Form(""),
    summary: str = Form(""),
    problem: str = Form(...),
    diagnosis: str = Form(""),
    solution: str = Form(...),
    result: str = Form(""),
    images: str = Form("[]"),
    published: bool = Form(True),
):

    require_admin(request)

    title = title.strip()
    url =  url.strip()
    technology = technology.strip()
    summary = summary.strip()
    problem = problem.strip()
    diagnosis = diagnosis.strip()
    solution = solution.strip()
    result = result.strip()

    if not title:

        raise HTTPException(
            status_code=400,
            detail="The title is required.",
        )

    if not problem:

        raise HTTPException(
            status_code=400,
            detail="The problem description is required.",
        )

    if not solution:

        raise HTTPException(
            status_code=400,
            detail="The solution is required.",
        )

    normalized_images = normalize_images(images)

    now = int(time.time())

    if USE_POSTGRES:

        sql = """
            INSERT INTO cases (
                title,
                url,
                technology,
                summary,
                problem,
                diagnosis,
                solution,
                result,
                image_paths,
                published,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            RETURNING *
        """

    else:

        sql = """
            INSERT INTO cases (
                title,
                url,
                technology,
                summary,
                problem,
                diagnosis,
                solution,
                result,
                image_paths,
                published,
                created_at,
                updated_at
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """

    with get_db() as connection:

        values = (
            title,
            url,
            technology,
            summary,
            problem,
            diagnosis,
            solution,
            result,
            json.dumps(normalized_images),
            int(published),
            now,
            now,
        )

        if USE_POSTGRES:

            row = connection.execute(
                sql,
                values,
            ).fetchone()

        else:

            cursor = connection.execute(
                sql,
                values,
            )

            row = connection.execute(
                "SELECT * FROM cases WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()

    return case_to_dict(row)


# ============================================================
# UPDATE CASE STUDY
# ============================================================

@app.put("/api/cases/{case_id}")
def update_case(
    case_id: int,
    request: Request,
    title: str = Form(...),
    url: str = Form(""),
    technology: str = Form(""),
    summary: str = Form(""),
    problem: str = Form(...),
    diagnosis: str = Form(""),
    solution: str = Form(...),
    result: str = Form(""),
    images: str = Form("[]"),
    published: bool = Form(True),
):

    require_admin(request)

    title = title.strip()
    url =  url.strip()
    technology = technology.strip()
    summary = summary.strip()
    problem = problem.strip()
    diagnosis = diagnosis.strip()
    solution = solution.strip()
    result = result.strip()

    if not title or not problem or not solution:

        raise HTTPException(
            status_code=400,
            detail="Title, problem, and solution are required.",
        )

    normalized_images = normalize_images(images)

    now = int(time.time())

    ph = placeholder()

    with get_db() as connection:

        old_row = connection.execute(
            f"SELECT * FROM cases WHERE id = {ph}",
            (case_id,),
        ).fetchone()

        if old_row is None:

            raise HTTPException(
                status_code=404,
                detail="Case study not found.",
            )

        old_images = normalize_images(
            old_row["image_paths"]
        )

        old_paths = image_paths(old_images)

        new_paths = image_paths(normalized_images)

        connection.execute(
            f"""
            UPDATE cases
            SET
                title = {ph},
                url = {ph},
                technology = {ph},
                summary = {ph},
                problem = {ph},
                diagnosis = {ph},
                solution = {ph},
                result = {ph},
                image_paths = {ph},
                published = {ph},
                updated_at = {ph}
            WHERE id = {ph}
            """,
            (
                title,
                url,
                technology,
                summary,
                problem,
                diagnosis,
                solution,
                result,
                json.dumps(normalized_images),
                int(published),
                now,
                case_id,
            ),
        )

        row = connection.execute(
            f"SELECT * FROM cases WHERE id = {ph}",
            (case_id,),
        ).fetchone()

    # Delete files only after the database transaction succeeds.
    # If an image is still referenced by the updated case,
    # it is not deleted.
    paths_to_delete = [
        path
        for path in old_paths
        if path not in new_paths
    ]

    if paths_to_delete:
        delete_unused_uploads(paths_to_delete)

    return case_to_dict(row)


# ============================================================
# DELETE CASE STUDY
# ============================================================

@app.delete("/api/cases/{case_id}")
def delete_case(
    case_id: int,
    request: Request,
):

    require_admin(request)

    ph = placeholder()

    with get_db() as connection:

        row = connection.execute(
            f"SELECT * FROM cases WHERE id = {ph}",
            (case_id,),
        ).fetchone()

        if row is None:

            raise HTTPException(
                status_code=404,
                detail="Case study not found.",
            )

        old_images = normalize_images(
            row["image_paths"]
        )

        paths_to_delete = image_paths(old_images)

        connection.execute(
            f"DELETE FROM cases WHERE id = {ph}",
            (case_id,),
        )

    delete_unused_uploads(paths_to_delete)

    return {
        "success": True,
        "deleted_id": case_id,
    }


# ============================================================
# ERROR HANDLER
# ============================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
):

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
        },
        headers=exc.headers,
    )