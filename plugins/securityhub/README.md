# SecurityHub Plugin

Fetches active AWS SecurityHub findings updated in the last N hours and surfaces
critical and high-severity issues in the executive daily brief.

## Required env vars

| Variable | Required | Description |
|---|---|---|
| `SECURITYHUB_AWS_REGION` | Yes | AWS region where SecurityHub is enabled |
| `SECURITYHUB_AWS_ACCESS_KEY_ID` | No | AWS access key (omit to use profile) |
| `SECURITYHUB_AWS_SECRET_ACCESS_KEY` | No | AWS secret key (omit to use profile) |
| `SECURITYHUB_AWS_PROFILE` | No | Named AWS profile (alternative to key pair) |
| `SECURITYHUB_MAX_FINDINGS` | No | Cap on findings fetched per run (default: `200`) |

Either `SECURITYHUB_AWS_ACCESS_KEY_ID` + `SECURITYHUB_AWS_SECRET_ACCESS_KEY` or
`SECURITYHUB_AWS_PROFILE` must be available, or the ambient IAM role must have
`securityhub:GetFindings` permission.

## What it fetches

Active findings (`RecordState=ACTIVE`) that are not suppressed or resolved and
were updated within the configured window. Paginated via the `get_findings`
paginator, capped at `SECURITYHUB_MAX_FINDINGS`.

Aggregated counts by severity (CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL) and by
compliance standard (CIS, PCI, FSBP, NIST, etc.) are included in the payload.

## Redaction

Account IDs (12-digit numbers) are replaced with `[ACCOUNT_ID]` in all ARN
fields. Resource ARNs in `resources[]` are collapsed to `service:resource` form
(e.g. `iam:role/admin`) before being sent to the LLM.

## IAM permissions required

```json
{
  "Effect": "Allow",
  "Action": ["securityhub:GetFindings"],
  "Resource": "*"
}
```
