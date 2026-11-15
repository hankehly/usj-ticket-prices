"""Lambda entry points: the scheduled Snapshot runs and the data file build."""

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
    on_new_data: Callable[[], None],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> SnapshotResult:
    """Take today's Snapshot, alerting if the day's final run leaves it incomplete.

    `on_new_data` is called when the run stored anything, so that whatever is
    derived from the Snapshots can be brought up to date.
    """
    result = take_snapshot(snapshot_date(now()), store, archive, now=now)
    try:
        if event.get("final") and not result.complete:
            alert(
                f"USJ ticket prices: Snapshot {result.snapshot_date} is incomplete",
                f"The Snapshot for {result.snapshot_date} (Japan time) is still missing "
                f"{len(result.missing)} item(s) after the day's final run:\n\n"
                + "\n".join(result.missing),
            )
    finally:
        # Even if the alert could not be sent: a later run that finds nothing
        # missing would not get another chance to pass the new data on.
        if result.fetched:
            on_new_data()
    return result


def handler(event, context):
    import boto3

    from usj_ticket_prices.archive import S3Archive
    from usj_ticket_prices.store import HttpStore

    sns = boto3.client("sns")
    topic_arn = os.environ["ALERT_TOPIC_ARN"]
    lambda_client = boto3.client("lambda")
    build_function = os.environ["BUILD_FUNCTION_NAME"]

    def alert(subject: str, message: str) -> None:
        sns.publish(TopicArn=topic_arn, Subject=subject, Message=message)

    def start_build() -> None:
        # Asynchronous: this run does not wait for the build to finish.
        lambda_client.invoke(FunctionName=build_function, InvocationType="Event")

    result = run(
        event or {},
        HttpStore(),
        S3Archive(boto3.client("s3"), os.environ["SNAPSHOT_BUCKET"]),
        alert,
        on_new_data=start_build,
    )
    summary = {
        "snapshot_date": result.snapshot_date.isoformat(),
        "complete": result.complete,
        "fetched": len(result.fetched),
        "missing": result.missing,
    }
    print(json.dumps(summary))  # One line per run in the function's log.
    return summary


def build_handler(event, context):
    """Rebuild the data file from every stored Snapshot."""
    import boto3

    from usj_ticket_prices.archive import S3Archive
    from usj_ticket_prices.data_file import build_data_file
    from usj_ticket_prices.site import DATA_FILE, S3Site

    s3 = boto3.client("s3")
    body = build_data_file(S3Archive(s3, os.environ["SNAPSHOT_BUCKET"]))
    S3Site(s3, os.environ["SITE_BUCKET"]).write_data_file(body)
    summary = {"data_file": DATA_FILE, "bytes": len(body)}
    print(json.dumps(summary))  # One line per build in the function's log.
    return summary
