"""CDK app. Run through the pinned CLI: npx cdk <command> -c alert_email=<address>"""

from __future__ import annotations

import os

from aws_cdk import App, Environment

from infra.snapshot_stack import SnapshotStack

app = App()

# Supplied at deploy time so the address never lands in this public repo.
alert_email = app.node.try_get_context("alert_email")
if not alert_email:
    raise SystemExit("Pass the alert address: npx cdk deploy -c alert_email=you@example.com")

SnapshotStack(
    app,
    "UsjTicketPricesSnapshot",
    alert_email=alert_email,
    # The account comes from the credentials in use; the region is always Tokyo.
    env=Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region="ap-northeast-1"),
    termination_protection=True,
)

app.synth()
