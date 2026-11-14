import json

from aws_cdk import App, Environment
from aws_cdk.assertions import Match, Template

from infra.snapshot_stack import SnapshotStack


def synthesized() -> Template:
    stack = SnapshotStack(
        App(),
        "Test",
        alert_email="alerts@example.com",
        env=Environment(account="111111111111", region="ap-northeast-1"),
    )
    return Template.from_stack(stack)


def test_the_snapshot_bucket_is_private_versioned_and_outlives_the_stack():
    template = synthesized()

    template.has_resource(
        "AWS::S3::Bucket",
        {
            "DeletionPolicy": "Retain",
            "Properties": {
                "VersioningConfiguration": {"Status": "Enabled"},
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "BlockPublicPolicy": True,
                    "IgnorePublicAcls": True,
                    "RestrictPublicBuckets": True,
                },
            },
        },
    )


def test_runs_are_scheduled_in_japan_time_and_only_the_last_is_final():
    schedules = synthesized().find_resources("AWS::Scheduler::Schedule")

    runs = {
        resource["Properties"]["ScheduleExpression"]: json.loads(
            resource["Properties"]["Target"]["Input"]
        )
        for resource in schedules.values()
    }
    assert runs == {
        "cron(0 4 * * ? *)": {"final": False},
        "cron(0 7 * * ? *)": {"final": False},
        "cron(0 10 * * ? *)": {"final": True},
    }
    for resource in schedules.values():
        assert resource["Properties"]["ScheduleExpressionTimezone"] == "Asia/Tokyo"


def test_the_function_cannot_delete_stored_responses():
    policies = synthesized().find_resources("AWS::IAM::Policy")

    actions = [
        action
        for policy in policies.values()
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
    ]
    assert any(action.startswith("s3:PutObject") for action in actions)
    assert not any("Delete" in action for action in actions)


def test_alerts_go_to_the_address_given_at_deploy_time():
    synthesized().has_resource_properties(
        "AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "alerts@example.com"}
    )


def test_a_crashed_run_raises_an_alarm_and_is_not_retried_automatically():
    template = synthesized()

    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"MetricName": "Errors", "Threshold": 1, "AlarmActions": Match.any_value()},
    )
    template.has_resource_properties(
        "AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0}
    )


def test_only_one_run_executes_at_a_time():
    synthesized().has_resource_properties(
        "AWS::Lambda::Function", {"ReservedConcurrentExecutions": 1}
    )
