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


def policy_statements(template: Template, function_id: str) -> list[dict]:
    """The IAM statements granted to the role of the function with this construct id."""
    return [
        statement
        for policy in template.find_resources("AWS::IAM::Policy").values()
        if any(
            role["Ref"].startswith(f"{function_id}ServiceRole")
            for role in policy["Properties"]["Roles"]
        )
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]


def actions(statement: dict) -> list[str]:
    action = statement["Action"]
    return action if isinstance(action, list) else [action]


def test_neither_bucket_can_be_made_public():
    template = synthesized()

    template.resource_count_is("AWS::S3::Bucket", 2)
    template.all_resources_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )


def test_the_build_reads_the_snapshots_and_writes_to_the_site_bucket():
    synthesized().has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "usj_ticket_prices.handler.build_handler",
            "Environment": {
                "Variables": {
                    "SNAPSHOT_BUCKET": {"Ref": Match.string_like_regexp("^Snapshots")},
                    "SITE_BUCKET": {"Ref": Match.string_like_regexp("^Site")},
                }
            },
        },
    )


def test_the_build_can_write_nothing_but_the_data_file():
    statements = policy_statements(synthesized(), "BuildDataFile")

    writes = [
        statement
        for statement in statements
        if any(action.startswith("s3:Put") for action in actions(statement))
    ]
    assert len(writes) == 1
    (bucket_arn, key) = writes[0]["Resource"]["Fn::Join"][1]
    assert bucket_arn["Fn::GetAtt"][0].startswith("Site")
    assert key == "/data.json"


def test_a_snapshot_run_is_able_to_start_the_build():
    template = synthesized()

    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "usj_ticket_prices.handler.handler",
            "Environment": {
                "Variables": Match.object_like(
                    {"BUILD_FUNCTION_NAME": {"Ref": Match.string_like_regexp("^BuildDataFile")}}
                )
            },
        },
    )
    granted = [
        action
        for statement in policy_statements(template, "TakeSnapshot")
        for action in actions(statement)
    ]
    assert "lambda:InvokeFunction" in granted


def test_a_failed_build_raises_an_alarm():
    synthesized().has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "MetricName": "Errors",
            "Dimensions": [
                {
                    "Name": "FunctionName",
                    "Value": {"Ref": Match.string_like_regexp("^BuildDataFile")},
                }
            ],
            "AlarmActions": Match.any_value(),
        },
    )
