variable "aws_region" {
  description = "AWS region to deploy all resources into"
  type        = string
  default     = "us-east-1"
}

variable "aws_profile" {
  description = "Local AWS CLI profile name (blank = default credential chain)"
  type        = string
  default     = ""
}

variable "vpc_id" {
  description = "VPC ID to run ECS tasks in. Use \"default\" to auto-discover the account's default VPC."
  type        = string
  default     = "default"
}

variable "schedule_cron" {
  description = "EventBridge Scheduler cron expression, evaluated in schedule_timezone"
  type        = string
  default     = "cron(0 8 * * ? *)"
}

variable "schedule_timezone" {
  description = "IANA timezone for the schedule (e.g. America/New_York, America/Los_Angeles)"
  type        = string
  default     = "America/New_York"
}

variable "task_cpu" {
  description = "ECS Fargate task CPU units (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 512
}

variable "task_memory" {
  description = "ECS Fargate task memory in MB (must be compatible with task_cpu)"
  type        = number
  default     = 1024
}

variable "image_tag" {
  description = "Docker image tag to run (default: latest)"
  type        = string
  default     = "latest"
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention period in days"
  type        = number
  default     = 30
}