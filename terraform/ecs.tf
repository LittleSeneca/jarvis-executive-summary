resource "aws_ecs_cluster" "jarvis" {
  name = "jarvis"

  tags = { Project = "jarvis" }
}

resource "aws_cloudwatch_log_group" "jarvis" {
  name              = "/aws/jarvis/run-logs"
  retention_in_days = var.log_retention_days

  tags = { Project = "jarvis" }
}

resource "aws_ecs_task_definition" "jarvis" {
  family                   = "jarvis"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.jarvis_execution.arn
  task_role_arn            = aws_iam_role.jarvis_task.arn

  container_definitions = jsonencode([{
    name      = "jarvis"
    image     = "ghcr.io/littleseneca/jarvis-executive-summary:${var.image_tag}"
    essential = true

    # Each SSM parameter is injected as an env var with the same name as its key.
    # The for expression iterates over data.aws_ssm_parameter.jarvis (keyed by env var name).
    secrets = [for env_var, param in data.aws_ssm_parameter.jarvis : {
      name      = env_var
      valueFrom = param.arn
    }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.jarvis.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "jarvis"
      }
    }
  }])

  tags = { Project = "jarvis" }
}
