"""The bucket the public page is served from."""

from __future__ import annotations

DATA_FILE = "data.json"

# How long a browser or CDN may reuse the data file before asking again. The
# file changes at most a few times a day.
CACHE_SECONDS = 300


class S3Site:
    def __init__(self, s3_client, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket

    def write_data_file(self, body: bytes) -> None:
        self._s3.put_object(
            Bucket=self._bucket,
            Key=DATA_FILE,
            Body=body,
            ContentType="application/json",
            CacheControl=f"max-age={CACHE_SECONDS}",
        )
