from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import hashlib
import ipaddress
import os
from pathlib import Path
import re
import socket
import tempfile
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import httpx

from mybot.common.json_store import load_json, mutate_json


IMAGE_LIBRARY_ROOT = Path(__file__).resolve().parent.parent / "data" / "image_library"
INDEX_VERSION = 1
MAX_TAGS = 8
MAX_TAG_LENGTH = 24
MAX_OCR_LENGTH = 2000
MAX_SUMMARY_LENGTH = 200
DOWNLOAD_REDIRECT_LIMIT = 3
DOWNLOAD_TIMEOUT_SECONDS = 20.0
DOWNLOAD_CHUNK_SIZE = 64 * 1024
_TAG_SEPARATOR = re.compile(r"[\s,，、;；|]+")
_SAFE_FILENAME = re.compile(r"^[0-9a-f]{64}\.(?:jpg|png|gif|webp|bmp)$")


class ImageLibraryError(RuntimeError):
    """Base error for safe image-library operations."""


class InvalidImageError(ImageLibraryError):
    pass


class ImageTooLargeError(ImageLibraryError):
    pass


class ImageQuotaError(ImageLibraryError):
    pass


class ImageNotFoundError(ImageLibraryError):
    pass


class ImagePermissionError(ImageLibraryError):
    pass


class ImageDownloadError(ImageLibraryError):
    pass


@dataclass(frozen=True)
class StoredImageResult:
    status: str
    record: dict[str, Any]


def _normalize_numeric_id(value: str | int, field: str) -> str:
    normalized = str(value).strip()
    if not normalized.isdigit() or int(normalized) <= 0:
        raise ValueError(f"invalid_{field}")
    return str(int(normalized))


def normalize_tags(value: str | Iterable[str]) -> list[str]:
    if isinstance(value, str):
        candidates = _TAG_SEPARATOR.split(value.strip()) if value.strip() else []
    else:
        candidates = [str(item).strip() for item in value]

    tags: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        tag = candidate.strip().lstrip("#").strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH or any(ord(char) < 32 for char in tag):
            raise ValueError("invalid_image_tag")
        normalized = tag.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        tags.append(tag)
        if len(tags) > MAX_TAGS:
            raise ValueError("too_many_image_tags")
    return tags


def detect_image_format(content: bytes) -> tuple[str, str]:
    if content.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp", "image/webp"
    if content.startswith(b"BM"):
        return "bmp", "image/bmp"
    raise InvalidImageError("unsupported_image_format")


def validate_image_bytes(content: bytes, *, max_file_bytes: int) -> tuple[str, str]:
    if not content:
        raise InvalidImageError("empty_image")
    if len(content) > max_file_bytes:
        raise ImageTooLargeError("image_too_large")
    return detect_image_format(content)


def _group_root(group_id: str | int, root: Path) -> Path:
    return root / _normalize_numeric_id(group_id, "group_id")


def _index_path(group_id: str | int, root: Path) -> Path:
    return _group_root(group_id, root) / "index.json"


def _default_index() -> dict[str, Any]:
    return {"version": INDEX_VERSION, "next_id": 1, "images": []}


def _validated_images(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    images = data.get("images", [])
    if not isinstance(images, list):
        return []
    return [dict(record) for record in images if isinstance(record, dict)]


def _prepare_mutable_index(data: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        raise ImageLibraryError("invalid_image_index")
    version = data.get("version", INDEX_VERSION)
    if version != INDEX_VERSION:
        raise ImageLibraryError("unsupported_image_index_version")
    data["version"] = INDEX_VERSION
    images = data.setdefault("images", [])
    if not isinstance(images, list):
        raise ImageLibraryError("invalid_image_index")
    next_id = data.setdefault("next_id", 1)
    if isinstance(next_id, bool) or not isinstance(next_id, int) or next_id < 1:
        raise ImageLibraryError("invalid_image_index")
    return images


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_content_once(path: Path, content: bytes, digest: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if (
            not path.is_file()
            or path.stat().st_size != len(content)
            or _file_sha256(path) != digest
        ):
            raise ImageLibraryError("image_digest_collision")
        return

    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{digest[:12]}-",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise ImageLibraryError(f"image_file_write_failed: {path.name}") from exc


def store_image(
    group_id: str | int,
    content: bytes,
    *,
    tags: str | Iterable[str],
    saved_by: str | int,
    source_user_id: str | int,
    source_message_id: str | int | None,
    ocr_text: str = "",
    summary: str = "",
    max_file_bytes: int,
    max_group_bytes: int,
    max_group_images: int,
    root: Path = IMAGE_LIBRARY_ROOT,
) -> StoredImageResult:
    group_key = _normalize_numeric_id(group_id, "group_id")
    saver_key = _normalize_numeric_id(saved_by, "saved_by")
    source_user_key = _normalize_numeric_id(source_user_id, "source_user_id")
    normalized_tags = normalize_tags(tags)
    if not normalized_tags:
        raise ValueError("missing_image_tags")

    extension, media_type = validate_image_bytes(
        content,
        max_file_bytes=max_file_bytes,
    )
    digest = hashlib.sha256(content).hexdigest()
    file_name = f"{digest}.{extension}"
    image_path = _group_root(group_key, root) / "images" / file_name
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    record = {
        "id": 0,
        "digest": digest,
        "file_name": file_name,
        "media_type": media_type,
        "size_bytes": len(content),
        "tags": normalized_tags,
        "ocr_text": str(ocr_text).strip()[:MAX_OCR_LENGTH],
        "summary": str(summary).strip()[:MAX_SUMMARY_LENGTH],
        "source_message_id": (
            str(source_message_id).strip() if source_message_id is not None else ""
        ),
        "source_user_id": source_user_key,
        "saved_by": saver_key,
        "saved_at": now,
    }

    def mutator(data: dict[str, Any]) -> StoredImageResult:
        images = _prepare_mutable_index(data)
        for existing in images:
            if isinstance(existing, dict) and existing.get("digest") == digest:
                return StoredImageResult("duplicate", dict(existing))

        if len(images) >= max_group_images:
            raise ImageQuotaError("image_count_quota")
        used_bytes = sum(
            max(0, int(item.get("size_bytes", 0)))
            for item in images
            if isinstance(item, dict)
            and not isinstance(item.get("size_bytes", 0), bool)
            and str(item.get("size_bytes", 0)).lstrip("-").isdigit()
        )
        if used_bytes + len(content) > max_group_bytes:
            raise ImageQuotaError("image_size_quota")

        record["id"] = data["next_id"]
        data["next_id"] += 1
        _write_content_once(image_path, content, digest)
        images.append(record)
        return StoredImageResult("created", dict(record))

    return mutate_json(_index_path(group_key, root), _default_index(), mutator)


def list_images(
    group_id: str | int,
    *,
    root: Path = IMAGE_LIBRARY_ROOT,
) -> list[dict[str, Any]]:
    return _validated_images(load_json(_index_path(group_id, root), _default_index()))


def _find_image_record(
    images: list[dict[str, Any]],
    image_id: int,
) -> dict[str, Any]:
    if isinstance(image_id, bool) or int(image_id) <= 0:
        raise ImageNotFoundError("image_not_found")
    record = next(
        (
            item
            for item in images
            if isinstance(item, dict) and item.get("id") == int(image_id)
        ),
        None,
    )
    if record is None:
        raise ImageNotFoundError("image_not_found")
    return record


def add_image_tags(
    group_id: str | int,
    image_id: int,
    tags: str | Iterable[str],
    *,
    root: Path = IMAGE_LIBRARY_ROOT,
) -> dict[str, Any]:
    group_key = _normalize_numeric_id(group_id, "group_id")
    added_tags = normalize_tags(tags)
    if not added_tags:
        raise ValueError("missing_image_tags")

    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        record = _find_image_record(_prepare_mutable_index(data), image_id)
        record["tags"] = normalize_tags([*record.get("tags", []), *added_tags])
        return dict(record)

    return mutate_json(_index_path(group_key, root), _default_index(), mutator)


def remove_image_tags(
    group_id: str | int,
    image_id: int,
    tags: str | Iterable[str],
    *,
    root: Path = IMAGE_LIBRARY_ROOT,
) -> dict[str, Any]:
    group_key = _normalize_numeric_id(group_id, "group_id")
    removed_tags = normalize_tags(tags)
    if not removed_tags:
        raise ValueError("missing_image_tags")
    removed_keys = {tag.casefold() for tag in removed_tags}

    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        record = _find_image_record(_prepare_mutable_index(data), image_id)
        current_tags = normalize_tags(record.get("tags", []))
        record["tags"] = [
            tag for tag in current_tags if tag.casefold() not in removed_keys
        ]
        return dict(record)

    return mutate_json(_index_path(group_key, root), _default_index(), mutator)


def _search_score(record: dict[str, Any], terms: list[str]) -> int | None:
    tags = [str(tag).casefold() for tag in record.get("tags", []) if str(tag).strip()]
    ocr_text = str(record.get("ocr_text", "")).casefold()
    summary = str(record.get("summary", "")).casefold()
    score = 0
    for term in terms:
        term_score = 0
        if term in tags:
            term_score = max(term_score, 12)
        if any(term in tag or tag in term for tag in tags):
            term_score = max(term_score, 8)
        if term in ocr_text:
            term_score = max(term_score, 5)
        if term in summary:
            term_score = max(term_score, 3)
        if not term_score:
            return None
        score += term_score
    return score


def search_images(
    group_id: str | int,
    query: str,
    *,
    limit: int = 10,
    root: Path = IMAGE_LIBRARY_ROOT,
) -> list[dict[str, Any]]:
    terms = [term.casefold() for term in normalize_tags(query)]
    if not terms:
        return []

    matches: list[tuple[int, dict[str, Any]]] = []
    for record in list_images(group_id, root=root):
        score = _search_score(record, terms)
        if score is not None:
            matches.append((score, record))
    matches.sort(
        key=lambda item: (
            item[0],
            str(item[1].get("saved_at", "")),
            int(item[1].get("id", 0)),
        ),
        reverse=True,
    )
    return [record for _, record in matches[: max(0, limit)]]


def get_library_stats(
    group_id: str | int,
    *,
    root: Path = IMAGE_LIBRARY_ROOT,
) -> dict[str, Any]:
    images = list_images(group_id, root=root)
    tag_counts: dict[str, int] = {}
    for record in images:
        for tag in record.get("tags", []):
            label = str(tag).strip()
            if label:
                tag_counts[label] = tag_counts.get(label, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    size_bytes = 0
    for record in images:
        value = record.get("size_bytes", 0)
        if isinstance(value, bool):
            continue
        try:
            size_bytes += max(0, int(value))
        except (TypeError, ValueError):
            continue
    return {
        "count": len(images),
        "size_bytes": size_bytes,
        "top_tags": top_tags,
    }


def _record_path(
    group_id: str | int,
    record: dict[str, Any],
    root: Path,
) -> Path:
    file_name = str(record.get("file_name", ""))
    digest = str(record.get("digest", ""))
    if not _SAFE_FILENAME.fullmatch(file_name) or not file_name.startswith(f"{digest}."):
        raise ImageLibraryError("unsafe_image_record")
    images_root = (_group_root(group_id, root) / "images").resolve()
    path = images_root / file_name
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ImageNotFoundError("image_file_missing") from exc
    try:
        resolved.relative_to(images_root)
    except ValueError as exc:
        raise ImageLibraryError("unsafe_image_record") from exc
    if not resolved.is_file():
        raise ImageNotFoundError("image_file_missing")
    return resolved


def read_image_bytes(
    group_id: str | int,
    record: dict[str, Any],
    *,
    max_file_bytes: int,
    root: Path = IMAGE_LIBRARY_ROOT,
) -> bytes:
    path = _record_path(group_id, record, root)
    if path.stat().st_size > max_file_bytes:
        raise ImageTooLargeError("image_too_large")
    content = path.read_bytes()
    validate_image_bytes(content, max_file_bytes=max_file_bytes)
    if hashlib.sha256(content).hexdigest() != record.get("digest"):
        raise ImageLibraryError("image_digest_mismatch")
    return content


def delete_image(
    group_id: str | int,
    image_id: int,
    *,
    actor_id: str | int,
    allow_any: bool = False,
    root: Path = IMAGE_LIBRARY_ROOT,
) -> dict[str, Any]:
    group_key = _normalize_numeric_id(group_id, "group_id")
    actor_key = _normalize_numeric_id(actor_id, "actor_id")
    if isinstance(image_id, bool) or int(image_id) <= 0:
        raise ImageNotFoundError("image_not_found")

    def mutator(data: dict[str, Any]) -> dict[str, Any]:
        images = _prepare_mutable_index(data)
        record = _find_image_record(images, image_id)
        target_index = images.index(record)
        permitted_ids = {
            str(record.get("saved_by", "")),
            str(record.get("source_user_id", "")),
        }
        if not allow_any and actor_key not in permitted_ids:
            raise ImagePermissionError("image_delete_denied")

        path = _record_path(group_key, record, root)
        path.unlink()
        images.pop(target_index)
        return dict(record)

    return mutate_json(_index_path(group_key, root), _default_index(), mutator)


def _validate_remote_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageDownloadError("unsafe_image_url")
    if parsed.username or parsed.password:
        raise ImageDownloadError("unsafe_image_url")
    hostname = parsed.hostname.rstrip(".").casefold()
    if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
        raise ImageDownloadError("unsafe_image_url")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return url, hostname
    if not address.is_global:
        raise ImageDownloadError("unsafe_image_url")
    return url, hostname


def _resolve_public_host(hostname: str) -> None:
    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ImageDownloadError("image_host_unavailable") from exc
    if not addresses:
        raise ImageDownloadError("image_host_unavailable")
    for value in addresses:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ImageDownloadError("unsafe_image_url") from exc
        if not address.is_global:
            raise ImageDownloadError("unsafe_image_url")


async def download_image(
    url: str,
    *,
    max_file_bytes: int,
) -> bytes:
    current_url = str(url).strip()
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        trust_env=False,
    ) as client:
        for redirect_count in range(DOWNLOAD_REDIRECT_LIMIT + 1):
            current_url, hostname = _validate_remote_url(current_url)
            await asyncio.to_thread(_resolve_public_host, hostname)
            try:
                async with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        if redirect_count >= DOWNLOAD_REDIRECT_LIMIT:
                            raise ImageDownloadError("too_many_image_redirects")
                        location = response.headers.get("location")
                        if not location:
                            raise ImageDownloadError("invalid_image_redirect")
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_length = response.headers.get("content-length", "")
                    if content_length.isdigit() and int(content_length) > max_file_bytes:
                        raise ImageTooLargeError("image_too_large")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK_SIZE):
                        size += len(chunk)
                        if size > max_file_bytes:
                            raise ImageTooLargeError("image_too_large")
                        chunks.append(chunk)
                    content = b"".join(chunks)
                    validate_image_bytes(content, max_file_bytes=max_file_bytes)
                    return content
            except ImageLibraryError:
                raise
            except (httpx.HTTPError, OSError) as exc:
                raise ImageDownloadError("image_download_failed") from exc
    raise ImageDownloadError("image_download_failed")


def read_local_image(path_value: str, *, max_file_bytes: int) -> bytes:
    try:
        path = Path(path_value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ImageDownloadError("image_file_unavailable") from exc
    if not path.is_file():
        raise ImageDownloadError("image_file_unavailable")
    if path.stat().st_size > max_file_bytes:
        raise ImageTooLargeError("image_too_large")
    content = path.read_bytes()
    validate_image_bytes(content, max_file_bytes=max_file_bytes)
    return content
