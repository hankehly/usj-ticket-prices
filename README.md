# USJ Ticket Prices

Tracks the published prices of Universal Studios Japan tickets over time. Once a day it takes a Snapshot of the price calendars on the official English web ticket store (usjticketing.com) and stores every response untouched, so that price changes the store itself doesn't show can be charted later.

This project is not affiliated with Universal Studios Japan or the store's operator.

## Where things are

| Path | What it holds |
| --- | --- |
| `GLOSSARY.md` | The project's vocabulary (Snapshot, Visit Date, Dynamic Pricing and so on) |
| `docs/adr/` | Decisions that would be hard to reverse, and why they were made |
| `src/usj_ticket_prices/` | The Snapshot code, which runs as an AWS Lambda function |
| `infra/` | The AWS resources, defined with AWS CDK in Python |
| `tests/` | Tests, which use saved store responses and never touch the network |

Planned work is tracked in GitHub Issues.

## Requirements

- [uv](https://docs.astral.sh/uv/), which installs Python 3.13 and the Python dependencies
- Node.js 20 or later, which runs the AWS CDK command
- AWS credentials for the target account, for deploying only

## Running the tests

```bash
uv sync
uv run pytest
```

## Deploying

Everything deploys to the Tokyo region (`ap-northeast-1`) of whichever AWS account your credentials belong to.

```bash
npm install

# Once per AWS account
npx cdk bootstrap

# Each deploy. The address receives failure alerts and is never stored in this repo.
npx cdk deploy -c alert_email=you@example.com
```

AWS sends that address a confirmation email after the first deploy. Alerts are not delivered until you click the link in it.

## How a Snapshot works

- Runs start at 04:00, 07:00 and 10:00 Japan time. A Snapshot belongs to the Japan-time date it ran on.
- A Snapshot is write-once. Each run fetches only what is still missing, so the later runs act as retries and normally make no requests.
- If the Snapshot is still incomplete after the 10:00 run, one alert email is sent.
- Requests to the store are spaced 3 seconds apart and carry a User-Agent that names this project.
