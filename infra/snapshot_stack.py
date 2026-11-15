"""AWS resources for the daily Snapshot and the data file built from it."""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack, TimeZone
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

from usj_ticket_prices.site import DATA_FILE

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

        code = lambda_.Code.from_asset(str(SOURCE_DIR), exclude=["**/__pycache__", "**/*.pyc"])

        take_snapshot = lambda_.Function(
            self,
            "TakeSnapshot",
            description="Takes the daily Snapshot of the ticket store's price calendars",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="usj_ticket_prices.handler.handler",
            code=code,
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

        # The public page is served from this bucket. The bucket itself stays
        # private: nothing in it is readable except through whatever is put in
        # front of it.
        site = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
        )

        build_data_file = lambda_.Function(
            self,
            "BuildDataFile",
            description="Builds the page's data file from every stored Snapshot",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="usj_ticket_prices.handler.build_handler",
            code=code,
            # Every build reads the whole history: about three S3 requests per
            # Snapshot, so a few seconds per year of Snapshots.
            timeout=Duration.minutes(5),
            memory_size=512,
            environment={
                "SNAPSHOT_BUCKET": bucket.bucket_name,
                "SITE_BUCKET": site.bucket_name,
            },
            log_group=logs.LogGroup(
                self,
                "BuildDataFileLogs",
                retention=logs.RetentionDays.THREE_MONTHS,
                removal_policy=RemovalPolicy.DESTROY,
            ),
        )
        # The build can read every stored response but change none of them,
        # and the data file is the only object it can write.
        bucket.grant_read(build_data_file)
        site.grant_put(build_data_file, DATA_FILE)

        # A Snapshot run that stored anything starts a build. Unlike a run, a
        # build is safe to repeat, so Lambda's automatic retries stay on.
        build_data_file.grant_invoke(take_snapshot)
        take_snapshot.add_environment("BUILD_FUNCTION_NAME", build_data_file.function_name)

        build_failed = build_data_file.metric_errors(period=Duration.minutes(5)).create_alarm(
            self,
            "BuildFailed",
            alarm_description="A build of the data file crashed or timed out",
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        build_failed.add_alarm_action(cloudwatch_actions.SnsAction(alerts))

        # Invoke this function by hand to rebuild the data file at any time.
        CfnOutput(self, "BuildDataFileFunctionName", value=build_data_file.function_name)
