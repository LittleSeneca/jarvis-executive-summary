data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# ECS Task Execution Role
# Used by ECS infrastructure to pull the image and fetch SSM secrets before
# the container starts. Never assumed by application code.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "jarvis_execution" {
  name = "jarvis-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = "jarvis" }
}

resource "aws_iam_role_policy_attachment" "jarvis_execution_managed" {
  role       = aws_iam_role.jarvis_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "jarvis_execution_ssm" {
  name = "jarvis-ssm-read"
  role = aws_iam_role.jarvis_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameters",
          "ssm:GetParameter",
          "ssm:GetParametersByPath",
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/jarvis/*"
      },
      {
        # Allow decryption of SSM SecureString params using the AWS-managed key
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com"
          }
        }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# ECS Task Role
# Assumed by the running container for AWS SDK calls (SecurityHub, Cost Explorer).
# All other plugins use credentials fetched from SSM.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "jarvis_task" {
  name = "jarvis-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = "jarvis" }
}

resource "aws_iam_role_policy" "jarvis_task_aws" {
  name = "jarvis-task-aws-permissions"
  role = aws_iam_role.jarvis_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "securityhub:GetFindings",
          "securityhub:DescribeHub",
          "securityhub:ListFindings",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ce:GetCostAndUsage",
          "ce:GetCostForecast",
        ]
        Resource = "*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# EventBridge Scheduler Role
# Allows the scheduler to call ECS RunTask and pass the task roles to ECS.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "jarvis_scheduler" {
  name = "jarvis-scheduler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = "jarvis" }
}

resource "aws_iam_role_policy" "jarvis_scheduler_run_task" {
  name = "jarvis-scheduler-run-task"
  role = aws_iam_role.jarvis_scheduler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = aws_ecs_task_definition.jarvis.arn
      },
      {
        Effect = "Allow"
        Action = ["iam:PassRole"]
        Resource = [
          aws_iam_role.jarvis_execution.arn,
          aws_iam_role.jarvis_task.arn,
        ]
      },
    ]
  })
}
