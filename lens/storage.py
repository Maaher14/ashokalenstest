"""Internal object keys only. No public or presigned media URLs."""

from pathlib import Path
from tempfile import SpooledTemporaryFile
from flask import current_app


def local_path(key):
    root = Path(current_app.config["MEDIA_ROOT"]).resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError("Invalid internal storage key")
    return path


def s3():
    return current_app.extensions["s3"]


def put(path, key, mime):
    if current_app.config["STORAGE"] == "s3":
        s3().upload_file(
            str(path),
            current_app.config["S3_BUCKET"],
            key,
            ExtraArgs={"ContentType": mime, "ServerSideEncryption": "AES256"},
        )
    else:
        dest = local_path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copyfile(path, dest)


def download(key, dest):
    if current_app.config["STORAGE"] == "s3":
        s3().download_file(current_app.config["S3_BUCKET"], key, str(dest))
    else:
        import shutil

        shutil.copyfile(local_path(key), dest)


def open_file(key):
    if current_app.config["STORAGE"] == "s3":
        file = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
        try:
            s3().download_fileobj(current_app.config["S3_BUCKET"], key, file)
            file.seek(0)
            return file
        except BaseException:
            file.close()
            raise
    return local_path(key).open("rb")


def delete(key):
    if current_app.config["STORAGE"] == "s3":
        s3().delete_object(Bucket=current_app.config["S3_BUCKET"], Key=key)
    else:
        local_path(key).unlink(missing_ok=True)
