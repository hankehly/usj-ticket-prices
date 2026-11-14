"""Lambda entry point for the scheduled Snapshot runs."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime

from usj_ticket_prices.snapshot import (
    Archive,
    SnapshotResult,
    Store,
    snapshot_date,
    take_snapshot,
)


def run(
    event: dict,
    store: Store,
    archive: Archive,
    alert: Callable[[str, str], None],
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SnapshotResult:
    """Take today's Snapshot, alerting if the day's final run leaves it incomplete."""
    result = take_snapshot(snapshot_date(now()), store, archive, now=now)
    if event.get("final") and not result.complete:
        alert(
            f"USJ ticket prices: Snapshot {result.snapshot_date} is incomplete",
            f"The Snapshot for {result.snapshot_date} (Japan time) is still missing "
            f"{len(result.missing)} item(s) after the day's final run:\n\n"
            + "\n".join(result.missing),
        )
    return result


def handler(event, context):
    import boto3

    from usj_ticket_prices.archive import S3Archive
    from usj_ticket_prices.store import HttpStore

    sns = boto3.client("sns")
    topic_arn = os.environ["ALERT_TOPIC_ARN"]

    def alert(subject: str, message: str) -> None:
        sns.publish(TopicArn=topic_arn, Subject=subject, Message=message)

    result = run(
        event or {},
        HttpStore(),
        S3Archive(boto3.client("s3"), os.environ["SNAPSHOT_BUCKET"]),
        alert,
    )
    summary = {
        "snapshot_date": result.snapshot_date.isoformat(),
        "complete": result.complete,
        "fetched": len(result.fetched),
        "missing": result.missing,
    }
    print(json.dumps(summary))  # One line per run in the function's log.
    return summary
