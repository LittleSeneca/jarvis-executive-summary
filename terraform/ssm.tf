# All Jarvis runtime configuration lives in SSM under /jarvis/<VAR_NAME>.
#
# Terraform does NOT create or own these parameters — they are created and
# updated exclusively by scripts/sync_env_to_ssm.sh (called by the
# null_resource below). The data sources read existing parameters so their
# ARNs can be wired into the ECS task definition.

locals {
  ssm_params = toset([
    # Core
    "ENABLED_PLUGINS",
    "LOG_LEVEL",
    "RUN_WINDOW_HOURS",
    "JARVIS_DRY_RUN",
    "JARVIS_OUTPUT_DIR",

    # Groq
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "GROQ_REQUESTS_PER_MINUTE",
    "GROQ_TOKENS_PER_MINUTE",
    "GROQ_WORKER_CONCURRENCY",
    "GROQ_MAX_RETRIES",

    # Slack
    "SLACK_BOT_TOKEN",
    "SLACK_TARGET_TYPE",
    "SLACK_TARGET_ID",
    "SLACK_USERNAME",
    "SLACK_ICON_EMOJI",

    # Site24x7
    "SITE24X7_ZOHO_REFRESH_TOKEN",
    "SITE24X7_CLIENT_ID",
    "SITE24X7_CLIENT_SECRET",
    "SITE24X7_DATACENTER",

    # AWS SecurityHub
    # Note: in ECS the task role provides AWS credentials; these are only needed
    # for local runs. Leave blank in .env when running in ECS.
    "SECURITYHUB_AWS_REGION",
    "SECURITYHUB_AWS_ACCESS_KEY_ID",
    "SECURITYHUB_AWS_SECRET_ACCESS_KEY",
    "SECURITYHUB_MAX_FINDINGS",

    # AWS Billing
    # Same note as SecurityHub — task role covers auth in ECS.
    "BILLING_AWS_REGION",
    "BILLING_AWS_ACCESS_KEY_ID",
    "BILLING_AWS_SECRET_ACCESS_KEY",
    "BILLING_CURRENCY",
    "BILLING_GROUP_BY",

    # Drata
    "DRATA_API_KEY",
    "DRATA_BASE_URL",

    # Gmail
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "GMAIL_REFRESH_TOKEN",
    "GMAIL_USER",
    "GMAIL_QUERY",

    # GitHub
    "GITHUB_TOKEN",
    "GITHUB_USER",
    "GITHUB_ORGS",
    "GITHUB_REPOS",
    "GITHUB_STALE_PR_DAYS",

    # Weather
    "WEATHER_ZIP_CODE",
    "WEATHER_COUNTRY_CODE",
    "WEATHER_UNITS",

    # News
    "NEWS_FEEDS",
    "NEWS_ITEMS_PER_FEED",
    "NEWS_DEDUPE",

    # Stocks
    "STOCKS_TICKERS",
    "STOCKS_INCLUDE_INDICES",
    "STOCKS_NEWS_PER_TICKER",
    "STOCKS_PROVIDER",
    "ALPHA_VANTAGE_API_KEY",

    # OSINT / Threat Intel
    "OSINT_SOURCES",
    "OSINT_NVD_API_KEY",
    "OSINT_URLHAUS_API_KEY",
    "OSINT_THREATFOX_API_KEY",
    "OSINT_OTX_API_KEY",

    # Trump
    "TRUMP_FEED_URL",
    "TRUMP_MAX_POSTS",
  ])
}

# ---------------------------------------------------------------------------
# Sync local .env → SSM
#
# Runs on first apply and re-runs whenever .env changes (keyed on MD5 hash).
# Requires the AWS CLI to be configured with credentials that have
# ssm:PutParameter on arn:aws:ssm:<region>:<account>:parameter/jarvis/*.
# ---------------------------------------------------------------------------

resource "null_resource" "sync_env_to_ssm" {
  triggers = {
    env_hash   = fileexists("${path.module}/../.env") ? filemd5("${path.module}/../.env") : "no-env-file"
    param_list = join(",", sort(tolist(local.ssm_params)))
  }

  provisioner "local-exec" {
    command = <<-EOT
      bash "${path.module}/../scripts/sync_env_to_ssm.sh" \
        --region "${var.aws_region}" \
        --profile "${var.aws_profile}"
    EOT
  }
}

# ---------------------------------------------------------------------------
# Read existing SSM parameters
#
# Terraform reads these (does not create them) so their ARNs can be wired
# into the ECS task definition. depends_on ensures the sync runs first so
# parameters exist before Terraform tries to look them up.
# ---------------------------------------------------------------------------

data "aws_ssm_parameter" "jarvis" {
  for_each   = local.ssm_params
  name       = "/jarvis/${each.key}"
  depends_on = [null_resource.sync_env_to_ssm]
}
