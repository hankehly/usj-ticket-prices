"""AWS resources for the daily Snapshot."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import Duration, RemovalPolicy, Stack, TimeZone
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cloudwatch_actions
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_scheduler as scheduler
from aws_cdk import aws_scheduler_targets as scheduler_targets
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct

SOURCE_DIR = Path(__file__).resolve().parent.parent / "src"

# Japan-time hours of the day's runs. Each run fetches only what the Snapshot
# still lacks, so the later runs act as retries. The last one raises the alert.
RUN_HOURS = (4, 7, 10)


class SnapshotStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, alert_email: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Stored responses are the source of truth and can never be re-fetched,
        # so the bucket outlives the stack and keeps every version.
        bucket = s3.Bucket(
            self,
            "Snapshots",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        alerts = sns.Topic(self, "Alerts", display_name="USJ ticket prices alerts")
        alerts.add_subscription(subscriptions.EmailSubscription(alert_email))

        take_snapshot = lambda_.Function(
            self,
            "TakeSnapshot",
            description="Takes the daily Snapshot of the ticket store's price calendars",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="usj_ticket_prices.handler.handler",
            code=lambda_.Code.from_asset(str(SOURCE_DIR), exclude=["**/__pycache__", "**/*.pyc"]),
            # About 70 requests paced 3 seconds apart take roughly 5 minutes.
            timeout=Duration.minutes(15),
            memory_size=256,
            # One run at a time. Overlapping runs would each pace their own
            # requests, hitting the store faster than agreed, and could
            # overwrite each other's manifest. A second run waits its turn.
            reserved_concurrent_executions=1,
            environment={
                "SNAPSHOT_BUCKET": bucket.bucket_name,
                "ALERT_TOPIC_ARN": alerts.topic_arn,
            },
            log_group=logs.LogGroup(
                self,
                "TakeSnapshotLogs",
                retention=logs.RetentionDays.THREE_MONTHS,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        # Read and put only: the function has no permission to delete a response.
        bucket.grant_read(take_snapshot)
        bucket.grant_put(take_snapshot)
        alerts.grant_publish(take_snapshot)
        # Runs happen only on schedule. An automatic re-run of the final run
        # could send the alert twice.
        take_snapshot.configure_async_invoke(retry_attempts=0)

        for hour in RUN_HOURS:
            final = hour == RUN_HOURS[-1]
            scheduler.Schedule(
                self,
                f"RunAt{hour:02d}",
                description=f"Snapshot run at {hour:02d}:00 Japan time",
                schedule=scheduler.ScheduleExpression.cron(
                    minute="0", hour=str(hour), time_zone=TimeZone.ASIA_TOKYO
                ),
                target=scheduler_targets.LambdaInvoke(
                    take_snapshot,
                    input=scheduler.ScheduleTargetInput.from_object({"final": final}),
                    retry_attempts=2,
                    max_event_age=Duration.hours(1),
                ),
            )

        # A run that crashes or times out never reaches its own incomplete
        # check, so it needs a separate alert.
        run_failed = take_snapshot.metric_errors(period=Duration.minutes(5)).create_alarm(
            self,
            "RunFailed",
            alarm_description="A Snapshot run crashed or timed out",
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        run_failed.add_alarm_action(cloudwatch_actions.SnsAction(alerts))
