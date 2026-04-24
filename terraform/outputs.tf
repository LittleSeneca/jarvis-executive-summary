output "cluster_arn" {
  description = "ECS cluster ARN"
  value       = aws_ecs_cluster.jarvis.arn
}

output "task_definition_arn" {
  description = "Latest active task definition ARN"
  value       = aws_ecs_task_definition.jarvis.arn
}

output "log_group_name" {
  description = "CloudWatch log group name"
  value       = aws_cloudwatch_log_group.jarvis.name
}

output "task_security_group_id" {
  description = "Security group ID attached to ECS tasks"
  value       = aws_security_group.jarvis_task.id
}

output "subnet_ids" {
  description = "Subnet IDs used by ECS tasks (comma-separated for use in CLI commands)"
  value       = join(",", local.subnet_ids)
}

output "scheduler_arn" {
  description = "EventBridge Scheduler schedule ARN"
  value       = aws_scheduler_schedule.jarvis_daily.arn
}

output "manual_run_command" {
  description = "CLI command to trigger a manual ECS run"
  value       = <<-EOT
    aws ecs run-task \
      --cluster ${aws_ecs_cluster.jarvis.name} \
      --task-definition ${aws_ecs_task_definition.jarvis.family} \
      --launch-type FARGATE \
      --network-configuration "awsvpcConfiguration={subnets=[${join(",", local.subnet_ids)}],securityGroups=[${aws_security_group.jarvis_task.id}],assignPublicIp=${var.assign_public_ip ? "ENABLED" : "DISABLED"}}" \
      --region ${var.aws_region}
  EOT
}
