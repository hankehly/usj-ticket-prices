"""Snapshot storage in S3.

Layout, under one prefix per Snapshot date:

    snapshots/2026-11-15/product-list/studio-pass.json
    snapshots/2026-11-15/sku-list/139.json
    snapshots/2026-11-15/price-calendar/139.json
    snapshots/2026-11-15/manifest.json
"""

from __future__ import annotations

import json
from datetime import date, datetime

from botocore.exceptions import ClientError

MANIFEST = "manifest.json"


class S3Archive:
    def __init__(self, s3_client, bucket: str) -> None:
        self._s3 = s3_client
        self._bucket = bucket

    def stored_items(self, snapshot_date: date) -> set[str]:
        prefix = _prefix(snapshot_date)
        paginator = self._s3.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self._bucket, Prefix=prefix)
        items = {key[len(prefix) :] for key in pages.search("Contents[].Key") if key}
        items.discard(MANIFEST)
        return items

    def read(self, snapshot_date: date, item: str) -> bytes:
        response = self._s3.get_object(Bucket=self._bucket, Key=_prefix(snapshot_date) + item)
        with response["Body"] as body:
            return body.read()

    def write(
        self, snapshot_date: date, item: str, body: bytes, fetched_at: datetime
    ) -> bool:
        # IfNoneMatch makes S3 itself refuse to replace a stored response, so
        # write-once holds even if two runs overlap.
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=_prefix(snapshot_date) + item,
                Body=body,
                ContentType="application/json",
                Metadata={"fetched-at": fetched_at.isoformat()},
                IfNoneMatch="*",
            )
        except ClientError as error:
            # An overlapping run stored this response first. That is the
            # outcome write-once asks for, not a failure.
            if error.response["Error"]["Code"] == "PreconditionFailed":
                return False
            raise
        return True

    def write_manifest(self, snapshot_date: date, manifest: dict) -> None:
        # The manifest describes the Snapshot's current state, so unlike the
        # responses it is rewritten by every run.
        self._s3.put_object(
            Bucket=self._bucket,
            Key=_prefix(snapshot_date) + MANIFEST,
            Body=json.dumps(manifest, indent=2).encode(),
            ContentType="application/json",
        )


def _prefix(snapshot_date: date) -> str:
    return f"snapshots/{snapshot_date.isoformat()}/"
