# Jarvis — Infrastructure Specification

**Status:** Draft — under review  
**Author:** operator-defined  
**Date:** 2026-04-24  
**Scope:** CI/CD image pipeline, AWS scheduled execution, Terraform layout

---

## 1. Goals

| Goal | Detail |
|------|--------|
| Self-contained | All infrastructure code lives in this repo under `terraform/`. No external IaC repo. |
| Automated image builds | Merging to `main` triggers a GitHub Actions workflow that builds and pushes the Docker image to GitHub Container Registry (ghcr.io). |
| Scheduled execution | AWS EventBridge Scheduler triggers an ECS Fargate task on a configurable schedule. The task runs the container, posts to Slack, and exits. |
| Secret management | All runtime credentials live in AWS SSM Parameter Store. A script syncs values from your local `.env` file into SSM. The ECS task injects them as environment variables at launch. |
| Least privilege | Two IAM roles: one execution role (ECS infrastructure) and one task role (application permissions). Neither role has admin access. |
| Operable | Logs go to CloudWatch Logs. Failed runs are visible without SSH or container access. |

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  GitHub                                                         │
│                                                                 │
│  main branch ──push──► GitHub Actions Workflow                  │
│                              │                                  │
│                              ▼                                  │
│                     docker build + push                         │
│                              │                                  │
│                              ▼                                  │
│                   ghcr.io/littleseneca/                         │
│                   jarvis-executive-summary:latest               │
│                   jarvis-executive-summary:<sha>                │
└─────────────────────────────────────────────────────────────────┘
                              │  image pull (public, no auth)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  AWS                                                            │
│                                                                 │
│  EventBridge Scheduler ──trigger──► ECS Fargate Task           │
│  (timezone-aware cron)                    │                     │
│                          ┌────────────────┼───────────────┐    │
│                          │                │               │    │
│                          ▼                ▼               ▼    │
│                    SSM Parameter    CloudWatch       External   │
│                    Store (secrets)  Logs (stdout)   APIs        │
│                    injected as env  /aws/jarvis/    (Slack,     │
│                    vars at launch   run-logs         Groq, etc) │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Inventory

### 3.1 GitHub Container Registry (ghcr.io)

- Repository: `ghcr.io/littleseneca/jarvis-executive-summary`
- Visibility: **public** — the image contains no secrets; all credentials are injected at runtime via SSM
- Tags pushed on each merge to `main`:
  - `latest`
  - `<git-sha>` (full 40-char SHA for precise rollbacks)

A public image means ECS can pull it without any `repositoryCredentials` configuration, keeping the task definition simple.

### 3.2 GitHub Actions Workflow

**File:** `.github/workflows/build-push.yml`  
**Triggers:** `pull_request` targeting `main` + `push` to `main`

| Event | Build | Push to ghcr.io |
|-------|-------|-----------------|
| PR opened / commit pushed to PR | yes | no |
| Merge to `main` | yes | yes (`latest` + `<sha>`) |

A successful build on a PR is used as an acceptance gate — if the image doesn't build, the PR can't merge. The push step is conditional on `github.ref == 'refs/heads/main'` within the same job, so no separate workflow file is needed.

The workflow does **not** deploy or touch AWS. ECS always pulls `latest` at task launch time.

**Caching strategy:**  
Docker layer caching uses the GitHub Actions cache (`type=gha`, `mode=max`). This exports all intermediate layers, not just the final image, so subsequent builds skip unchanged layers. The `Dockerfile` is already structured to maximise cache hits: `pyproject.toml` is copied and dependencies are installed before source code is copied, so a code-only change does not invalidate the dependency install layer.

### 3.3 AWS ECS Fargate

- **Cluster:** `jarvis`
- **Task definition:** `jarvis` family
  - CPU: `512` (.5 vCPU) — configurable via variable
  - Memory: `1024` MB — configurable via variable
  - Image: `ghcr.io/littleseneca/jarvis-executive-summary:latest`
  - Log driver: `awslogs` → CloudWatch log group `/aws/jarvis/run-logs`
  - Environment variables: all injected from SSM Parameter Store at task launch
  - Network mode: `awsvpc`
- **Launch type:** Fargate — no EC2 instances to manage
- **Task lifecycle:** EventBridge calls `RunTask`; the container runs, posts to Slack, exits 0. ECS does not restart it — this is not a service

**Cost estimate:** ~$0.004 per run (5-minute task at 0.5 vCPU / 1 GB). Daily schedule ≈ **$0.12/month**. There is no standing infrastructure cost between runs.

### 3.4 EventBridge Scheduler

- **Schedule name:** `jarvis-daily`
- **Target:** ECS `RunTask` against the `jarvis` cluster and task definition
- **Timezone:** configurable via `schedule_timezone` variable (e.g., `America/New_York`)
- **Cron expression:** configurable via `schedule_cron` variable (e.g., `cron(0 8 * * ? *)` for 8:00 AM daily in the configured timezone)
- **Flexible time window:** `OFF` (exact schedule)
- **Retry policy:** 0 retries — a failing run just misses that day; cascading retries create duplicate Slack posts
- **Scheduler execution role:** dedicated IAM role with `ecs:RunTask` and `iam:PassRole` scoped to the jarvis task definition ARN

EventBridge Scheduler natively supports timezone-aware schedules (distinct from legacy EventBridge Rules). No UTC conversion math needed.

### 3.5 AWS SSM Parameter Store

All secrets and configuration are stored as `SecureString` parameters under `/jarvis/<VARIABLE_NAME>`. They are injected into the ECS task as environment variables at launch via the `secrets` block in the task definition.

**How values get into SSM:**  
A `null_resource` in Terraform (`ssm.tf`) runs a `local-exec` provisioner that calls `scripts/sync_env_to_ssm.sh`. That script parses the local `.env` file and calls `aws ssm put-parameter` for each key-value pair. This runs on `terraform apply` and re-runs whenever the `.env` file changes (keyed on its MD5 hash). The script requires the AWS CLI to be configured locally with credentials that have `ssm:PutParameter` access.

Terraform also declares all expected SSM parameters as `aws_ssm_parameter` resources with `lifecycle { ignore_changes = [value] }` — this creates the parameters on first apply and lets the sync script update values without Terraform tracking or overwriting them.

Full parameter list mirrors `.env.example`. See §6 for the complete table.

### 3.6 IAM Roles

**ECS Task Execution Role** (`jarvis-execution-role`):  
Used by ECS infrastructure to fetch SSM secrets before the container starts. Managed policy `AmazonECSTaskExecutionRolePolicy` plus an inline policy granting `ssm:GetParameters` and `kms:Decrypt` scoped to `/jarvis/*` parameter ARNs.

**ECS Task Role** (`jarvis-task-role`):  
Assumed by the running container for AWS SDK calls. Grants only what the application needs:
- `securityhub:GetFindings`, `securityhub:DescribeHub` (SecurityHub plugin)
- `ce:GetCostAndUsage`, `ce:GetCostForecast` (Billing plugin)
- All other plugins use non-AWS credentials fetched from SSM

**EventBridge Scheduler Role** (`jarvis-scheduler-role`):  
Allows EventBridge to call `ecs:RunTask` and `iam:PassRole` (to pass the task execution role to ECS). Scoped to the jarvis task definition ARN.

### 3.7 Networking

Fargate tasks require a VPC, subnets, and a security group.

**VPC selection:**  
Controlled by the `vpc_id` Terraform variable. Accepted values:
- `"default"` — discovers and uses the account's default VPC and its subnets automatically (via `aws_vpc` and `aws_subnets` data sources)
- Any VPC ID (e.g., `"vpc-0abc123"`) — uses that VPC and discovers its subnets

The task is assigned a public IP (`assignPublicIp = ENABLED`) so it can reach the internet without a NAT Gateway. This is appropriate for a personal workload — the task only makes outbound connections.

Security group (`jarvis-task-sg`): allow all outbound, no inbound. The container never receives connections.

### 3.8 CloudWatch Logs

- **Log group:** `/aws/jarvis/run-logs` — created by Terraform
- **Retention:** 30 days (configurable via `log_retention_days` variable)
- Logs stream in real-time from the container's stdout/stderr
- To tail a run: `aws logs tail /aws/jarvis/run-logs --follow`

---

## 4. Terraform Layout

```
terraform/
├── main.tf                   # required_providers, provider config
├── variables.tf              # all input variables with defaults
├── outputs.tf                # cluster ARN, task def ARN, log group name
├── ecs.tf                    # cluster, task definition, CloudWatch log group
├── iam.tf                    # execution role, task role, scheduler role
├── scheduler.tf              # EventBridge Scheduler schedule
├── ssm.tf                    # SSM parameter resource declarations + sync null_resource
├── network.tf                # VPC/subnet data sources based on vpc_id variable
├── security_group.tf         # outbound-only task security group
└── terraform.tfvars.example  # example var values (no secrets)
```

### Variables (`variables.tf`)

| Variable | Default | Description |
|----------|---------|-------------|
| `aws_region` | `"us-east-1"` | AWS region to deploy all resources into |
| `aws_profile` | `""` | Local AWS CLI profile to use (blank = default credential chain) |
| `vpc_id` | `"default"` | VPC to launch tasks in; `"default"` uses the account default VPC |
| `schedule_cron` | `"cron(0 8 * * ? *)"` | EventBridge cron expression |
| `schedule_timezone` | `"America/New_York"` | IANA timezone for the cron expression |
| `task_cpu` | `512` | Fargate task CPU units |
| `task_memory` | `1024` | Fargate task memory in MB |
| `image_tag` | `"latest"` | ghcr.io image tag for the task definition |
| `log_retention_days` | `30` | CloudWatch log retention in days |

### Backend

**Local state** — `terraform.tfstate` is written to the `terraform/` directory. This is a personal single-operator project; local state is sufficient. Add `terraform/terraform.tfstate*` to `.gitignore` to avoid committing state.

```hcl
terraform {
  backend "local" {}
}
```

No S3 bucket or DynamoDB table required.

---

## 5. GitHub Actions Workflow Detail

```yaml
# .github/workflows/build-push.yml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write      # needed for the conditional push step

    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      # Login only when we intend to push (i.e. on merge to main).
      # On PRs this step is skipped; the build still runs unauthenticated.
      - name: Log in to ghcr.io
        if: github.ref == 'refs/heads/main' && github.event_name == 'push'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build (and push on main)
        uses: docker/build-push-action@v5
        with:
          context: .
          # push=true only on a merge to main; false on PRs (build-only)
          push: ${{ github.ref == 'refs/heads/main' && github.event_name == 'push' }}
          platforms: linux/amd64
          tags: |
            ghcr.io/${{ github.repository_owner }}/jarvis-executive-summary:latest
            ghcr.io/${{ github.repository_owner }}/jarvis-executive-summary:${{ github.sha }}
          # GHA layer cache — exports all intermediate layers (mode=max)
          # so dependency-install layers survive across PR commits
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

No AWS credentials needed in the workflow. The single job handles both PR and main-branch events; the `push:` flag is the only conditional.

---

## 6. `.env` → SSM Sync

### How it works

`scripts/sync_env_to_ssm.sh` is a bash script that:
1. Reads the `.env` file line by line
2. Skips blank lines and comments (`#`)
3. Splits each line on the first `=`
4. Calls `aws ssm put-parameter --name /jarvis/<KEY> --value "<VALUE>" --type SecureString --overwrite` for each pair

The script uses whatever AWS credentials and region are active in the environment (respects `AWS_PROFILE`, `AWS_REGION`, etc.).

### Terraform integration

`ssm.tf` contains a `null_resource` with a `local-exec` provisioner that calls the script:

```hcl
resource "null_resource" "sync_env_to_ssm" {
  triggers = {
    env_hash = filemd5("${path.module}/../.env")
  }

  provisioner "local-exec" {
    command = "bash ${path.module}/../scripts/sync_env_to_ssm.sh --region ${var.aws_region}"
  }
}
```

This runs on first `terraform apply` and re-runs automatically whenever the `.env` file changes. It does not run if `.env` has not changed.

### Updating a single secret

```bash
aws ssm put-parameter --name /jarvis/GROQ_API_KEY --value "new-key" \
  --type SecureString --overwrite
```

Or edit `.env` and re-run `terraform apply` — the hash trigger fires the sync.

---

## 7. SSM Parameter Reference

All parameters under `/jarvis/`. Terraform declares each one; the sync script populates values.

| Parameter | `.env` var | Sensitivity |
|-----------|-----------|-------------|
| `/jarvis/ENABLED_PLUGINS` | `ENABLED_PLUGINS` | String |
| `/jarvis/LOG_LEVEL` | `LOG_LEVEL` | String |
| `/jarvis/RUN_WINDOW_HOURS` | `RUN_WINDOW_HOURS` | String |
| `/jarvis/GROQ_API_KEY` | `GROQ_API_KEY` | SecureString |
| `/jarvis/GROQ_MODEL` | `GROQ_MODEL` | String |
| `/jarvis/GROQ_REQUESTS_PER_MINUTE` | `GROQ_REQUESTS_PER_MINUTE` | String |
| `/jarvis/GROQ_TOKENS_PER_MINUTE` | `GROQ_TOKENS_PER_MINUTE` | String |
| `/jarvis/SLACK_BOT_TOKEN` | `SLACK_BOT_TOKEN` | SecureString |
| `/jarvis/SLACK_TARGET_TYPE` | `SLACK_TARGET_TYPE` | String |
| `/jarvis/SLACK_TARGET_ID` | `SLACK_TARGET_ID` | String |
| `/jarvis/SLACK_USERNAME` | `SLACK_USERNAME` | String |
| `/jarvis/SLACK_ICON_EMOJI` | `SLACK_ICON_EMOJI` | String |
| `/jarvis/SITE24X7_ZOHO_CLIENT_ID` | `SITE24X7_ZOHO_CLIENT_ID` | SecureString |
| `/jarvis/SITE24X7_ZOHO_CLIENT_SECRET` | `SITE24X7_ZOHO_CLIENT_SECRET` | SecureString |
| `/jarvis/SITE24X7_ZOHO_REFRESH_TOKEN` | `SITE24X7_ZOHO_REFRESH_TOKEN` | SecureString |
| `/jarvis/SITE24X7_DATACENTER` | `SITE24X7_DATACENTER` | String |
| `/jarvis/SECURITYHUB_REGION` | `SECURITYHUB_REGION` | String |
| `/jarvis/BILLING_REGION` | `BILLING_REGION` | String |
| `/jarvis/DRATA_API_KEY` | `DRATA_API_KEY` | SecureString |
| `/jarvis/DRATA_BASE_URL` | `DRATA_BASE_URL` | String |
| `/jarvis/GMAIL_CLIENT_ID` | `GMAIL_CLIENT_ID` | SecureString |
| `/jarvis/GMAIL_CLIENT_SECRET` | `GMAIL_CLIENT_SECRET` | SecureString |
| `/jarvis/GMAIL_REFRESH_TOKEN` | `GMAIL_REFRESH_TOKEN` | SecureString |
| `/jarvis/GMAIL_USER` | `GMAIL_USER` | String |
| `/jarvis/GITHUB_TOKEN` | `GITHUB_TOKEN` | SecureString |
| `/jarvis/GITHUB_USER` | `GITHUB_USER` | String |
| `/jarvis/WEATHER_ZIP` | `WEATHER_ZIP` | String |
| `/jarvis/WEATHER_COUNTRY` | `WEATHER_COUNTRY` | String |
| `/jarvis/OPENWEATHERMAP_API_KEY` | `OPENWEATHERMAP_API_KEY` | SecureString |
| `/jarvis/NEWS_FEED_URLS` | `NEWS_FEED_URLS` | String |
| `/jarvis/STOCKS_TICKERS` | `STOCKS_TICKERS` | String |
| `/jarvis/STOCKS_PROVIDER` | `STOCKS_PROVIDER` | String |
| `/jarvis/OTX_API_KEY` | `OTX_API_KEY` | SecureString |
| `/jarvis/TRUMP_FEED_URL` | `TRUMP_FEED_URL` | String |

---

## 8. Operational Runbook

### First Deployment

```bash
# 1. Ensure AWS CLI is configured for the target account
aws sts get-caller-identity

# 2. Apply Terraform (creates all AWS resources + syncs .env to SSM)
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit as needed
terraform init
terraform plan
terraform apply

# 3. Verify parameters were loaded
aws ssm get-parameters-by-path --path /jarvis/ --with-decryption \
  --query 'Parameters[*].{Name:Name,Value:Value}'

# 4. Trigger a manual test run
aws ecs run-task \
  --cluster jarvis \
  --task-definition jarvis \
  --launch-type FARGATE \
  --network-configuration \
    "awsvpcConfiguration={subnets=[$(terraform output -raw subnet_ids)],assignPublicIp=ENABLED,securityGroups=[$(terraform output -raw task_security_group_id)]}"

# 5. Watch logs
aws logs tail /aws/jarvis/run-logs --follow
```

### Updating the Image

Merge to `main` — GitHub Actions builds and pushes `latest`. The next scheduled ECS run (or next manual run) pulls the new image.

### Changing the Schedule

Edit `schedule_cron` and/or `schedule_timezone` in `terraform.tfvars`, then `terraform apply`.

### Updating Secrets

Edit `.env` locally, then `terraform apply` (the hash trigger fires the sync script automatically).

Or update a single parameter directly:
```bash
aws ssm put-parameter --name /jarvis/SLACK_BOT_TOKEN --value "xoxb-..." \
  --type SecureString --overwrite
```

---

## 9. Out of Scope

| Item | Reason |
|------|--------|
| Multi-environment (dev/prod) | Single environment; personal/operational tool |
| Blue/green or canary deploys | One-shot task; no long-running service to roll over |
| Custom domain / ALB | No inbound traffic |
| Alerting / PagerDuty | CloudWatch log monitoring is sufficient for now |
| ECR (AWS Container Registry) | ghcr.io public is simpler; no cross-account pull setup needed |
| GitHub Actions AWS deployment | GHA only builds the image; EventBridge drives execution |
| Secrets rotation | Out of scope |
| Remote Terraform state (S3) | Local state is appropriate for a single operator |
