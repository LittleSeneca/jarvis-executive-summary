resource "aws_scheduler_schedule" "jarvis_daily" {
  name       = "jarvis-daily"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.schedule_cron
  schedule_expression_timezone = var.schedule_timezone

  target {
    arn      = aws_ecs_cluster.jarvis.arn
    role_arn = aws_iam_role.jarvis_scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.jarvis.arn
      launch_type         = "FARGATE"

      network_configuration {
        assign_public_ip = true
        security_groups  = [aws_security_group.jarvis_task.id]
        subnets          = local.subnet_ids
      }
    }

    retry_policy {
      maximum_retry_attempts = 0
    }
  }

}
