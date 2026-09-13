"""Private local and S3-compatible object storage backends."""

from __future__ import annotations

import mimetypes
import shutil
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import redirect, send_file


class StorageError(RuntimeError):
    pass


class LocalStorageBackend:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key):
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise StorageError("Cle de stockage locale invalide.")
        return target

    def put(self, key, stream, *, content_type=None):
        try:
            target = self._path(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            stream.seek(0)
            with target.open("wb") as destination:
                shutil.copyfileobj(stream, destination)
        except OSError as exc:
            raise StorageError("Echec de l'ecriture dans le stockage local.") from exc

    def delete(self, key):
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            return

    def exists(self, key):
        return self._path(key).is_file()

    def size(self, key):
        return self._path(key).stat().st_size

    def response(self, key, *, download_name=None, content_type=None):
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return send_file(
            path,
            mimetype=content_type or mimetypes.guess_type(download_name or key)[0],
            download_name=download_name,
            as_attachment=False,
            conditional=True,
        )

    def check(self):
        return self.root.is_dir()


class S3CompatibleStorageBackend:
    def __init__(self, config):
        self.bucket = config["R2_BUCKET"]
        self.client = boto3.client(
            "s3",
            endpoint_url=config["R2_ENDPOINT_URL"],
            aws_access_key_id=config["R2_ACCESS_KEY_ID"],
            aws_secret_access_key=config["R2_SECRET_ACCESS_KEY"],
            region_name=config.get("R2_REGION", "auto"),
        )

    def put(self, key, stream, *, content_type=None):
        extra = {"ContentType": content_type} if content_type else None
        stream.seek(0)
        try:
            kwargs = {"ExtraArgs": extra} if extra else {}
            self.client.upload_fileobj(stream, self.bucket, key, **kwargs)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Echec de l'upload vers le stockage objet.") from exc

    def delete(self, key):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Echec de suppression dans le stockage objet.") from exc

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                return False
            raise StorageError("Stockage objet indisponible.") from exc

    def size(self, key):
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
            return int(response["ContentLength"])
        except (BotoCoreError, ClientError, KeyError) as exc:
            raise StorageError("Impossible de verifier la taille de l'objet.") from exc

    def response(self, key, *, download_name=None, content_type=None):
        params = {"Bucket": self.bucket, "Key": key}
        if download_name:
            safe_name = download_name.replace('"', "")
            params["ResponseContentDisposition"] = f'inline; filename="{safe_name}"'
        try:
            url = self.client.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=300
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError("Impossible de preparer le telechargement.") from exc
        return redirect(url, code=302)

    def check(self):
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except (BotoCoreError, ClientError):
            return False


def required_r2_values(config):
    names = (
        "R2_ENDPOINT_URL",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
    )
    return [name for name in names if not config.get(name)]


def build_storage(config):
    backend = config.get("STORAGE_BACKEND", "local").lower()
    if backend == "local":
        return LocalStorageBackend(config["UPLOAD_FOLDER"])
    if backend in {"r2", "s3"}:
        missing = required_r2_values(config)
        if missing:
            raise StorageError("Configuration stockage objet incomplete: " + ", ".join(missing))
        return S3CompatibleStorageBackend(config)
    raise StorageError(f"Backend de stockage inconnu: {backend}")


def validate_production_storage(environment, backend, config):
    if environment != "production":
        return
    if backend == "local":
        raise RuntimeError("Le stockage local n'est pas autorise pour ClasseXP en production.")
    if backend not in {"r2", "s3"}:
        raise RuntimeError("Un stockage objet S3 compatible est obligatoire en production.")
    missing = required_r2_values(config)
    if missing:
        raise RuntimeError("Configuration stockage objet incomplete: " + ", ".join(missing))
