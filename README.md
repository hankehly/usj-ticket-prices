# USJ Ticket Prices

Tracks the published prices of Universal Studios Japan tickets over time. Once a day it takes a Snapshot of the price calendars on the official English web ticket store (usjticketing.com) and stores every response untouched, so that price changes the store itself doesn't show can be charted. After each Snapshot it rebuilds one data file, which is all the public page will read.

This project is not affiliated with Universal Studios Japan or the store's operator.

## Where things are

| Path | What it holds |
| --- | --- |
| `GLOSSARY.md` | The project's vocabulary (Snapshot, Visit Date, Dynamic Pricing and so on) |
| `docs/adr/` | Decisions that would be hard to reverse, and why they were made |
| `src/usj_ticket_prices/` | The Snapshot code and the data file build, which run as AWS Lambda functions |
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
npx cdk bootstrap -c alert_email=you@example.com

# Each deploy. The address receives failure alerts and is never stored in this repo.
npx cdk deploy -c alert_email=you@example.com
```

AWS sends that address a confirmation email after the first deploy. Alerts are not delivered until you click the link in it.

## How a Snapshot works

- Runs start at 04:00, 07:00 and 10:00 Japan time. A Snapshot belongs to the Japan-time date it ran on.
- A Snapshot is write-once. Each run fetches only what is still missing, so the later runs act as retries and normally make no requests.
- If the Snapshot is still incomplete after the 10:00 run, one alert email is sent.
- Requests to the store are spaced 3 seconds apart and carry a User-Agent that names this project.

## How the data file is built

- A Snapshot run that stored anything starts a build. The build reads every stored Snapshot and writes `data.json` to the bucket the page is served from. That bucket is private; the stored responses never leave their own bucket.
- The stored responses are the source of truth. Building again over the same Snapshots gives the same file, so the file can be rebuilt at any time. To rebuild by hand, invoke the function named in the stack's `BuildDataFileFunctionName` output:

  ```bash
  aws lambda invoke --function-name <BuildDataFileFunctionName> --region ap-northeast-1 /dev/stdout
  ```

- If a build crashes, the alert address gets an email.

The file covers one price series: the 1 Day Studio Pass for an Adult, in yen.

| Field | What it holds |
| --- | --- |
| `latest_snapshot` | The latest Snapshot's `date` (Japan time) and `taken_at`, the UTC time its price calendar was fetched |
| `upcoming_prices` | One entry per day from the latest Snapshot's date to the latest Visit Date any Snapshot has listed: `visit_date`, `state`, `price` |
| `final_prices` | The Final Price of every Visit Date ever observed, with its `weekday` (1 is Monday, 7 is Sunday). For a Visit Date still in the calendar this is its latest price |
| `change_by_lead_time` | For each `lead_time` of one day or more, longest first: `average_change`, the average difference from the Opening Price, and `visit_dates`, how many Visit Dates the average covers |
| `histories` | For every Visit Date ever observed, its `state`, `price` and the store's `sku_id` behind that price, in each Snapshot whose calendar reached it |
| `flags.sku_changes` | Each time the store's SKU behind the Guest Type differed from the Snapshot before. The price series carries on regardless |
| `flags.sku_conflicts` | Each Visit Date on which the store's data did not settle which SKU prices the Guest Type, with the SKUs involved |

A `state` is one of:

| State | Meaning |
| --- | --- |
| `available` | Listed and purchasable |
| `unavailable` | In the calendar but marked not purchasable (Unavailable), or in the calendar with no price for the Guest Type, in which case the price is `null`. The store's price is passed on but is left out of the Final Price, the Opening Price and the change by Lead Time |
| `not_listed` | Missing from the calendar, although this or an earlier Snapshot listed a date at least as late (Not Listed). The price is `null` |
| `sku_conflict` | Two SKUs were priced for the Guest Type, or the one SKU priced is a hidden SKU whose label and type code name different Guest Types. No price is picked, so the price is `null` |

A Guest Type is the label the store gives an SKU ("Adult"), not the SKU's id.

The Opening Price of a Visit Date is known only when the Snapshot of the day before was taken and did not list it. Every other Visit Date is left out of `change_by_lead_time`: those already listed in the very first Snapshot, and those that first appear right after a day with no Snapshot.
