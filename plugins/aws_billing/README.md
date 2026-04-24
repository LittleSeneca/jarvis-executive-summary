# AWS Billing Plugin

Fetches AWS Cost Explorer data — today's spend, month-to-date, quarter-to-date,
prior-period comparisons, and month/quarter-end forecasts — for the executive
daily brief.

## Required env vars

| Variable | Required | Description |
|---|---|---|
| `BILLING_AWS_REGION` | Yes | AWS region for the Cost Explorer endpoint |
| `BILLING_AWS_ACCESS_KEY_ID` | No | AWS access key (omit to use profile) |
| `BILLING_AWS_SECRET_ACCESS_KEY` | No | AWS secret key (omit to use profile) |
| `BILLING_AWS_PROFILE` | No | Named AWS profile (alternative to key pair) |
| `BILLING_CURRENCY` | No | Currency code for display (default: `USD`) |
| `BILLING_GROUP_BY` | No | Cost Explorer dimension to group by (default: `SERVICE`) |

Either `BILLING_AWS_ACCESS_KEY_ID` + `BILLING_AWS_SECRET_ACCESS_KEY` or
`BILLING_AWS_PROFILE` must be available, or the ambient IAM role must have
Cost Explorer permissions.

## What it fetches

Three parallel Cost Explorer `GetCostAndUsage` queries:

1. **Today** — daily granularity for the current calendar day.
2. **Month-to-date** — monthly granularity from the 1st of the month through today,
   plus the same elapsed-days period from the prior month for comparison.
3. **Quarter-to-date** — monthly granularity from the current calendar quarter start
   through today, plus the same elapsed-days period from the prior quarter.

A `GetCostForecast` call attempts month-end and quarter-end projections; if
insufficient history exists it fails silently and the forecast fields are `null`.

## Chunker

`chunker.py` provides a section-based chunker that splits the payload into
`today`, `mtd`, `qtd`, and `forecast` chunks for the map-reduce summarizer path.

## IAM permissions required

```json
{
  "Effect": "Allow",
  "Action": [
    "ce:GetCostAndUsage",
    "ce:GetCostForecast"
  ],
  "Resource": "*"
}
```

Note: Cost Explorer permissions must be granted at the AWS account (management
account for Organizations) level. The `ce:*` actions are global-service actions
and do not support resource-level restrictions.
