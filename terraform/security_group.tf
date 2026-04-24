resource "aws_security_group" "jarvis_task" {
  name        = "jarvis-task-sg"
  description = "Jarvis ECS task - outbound only, no inbound"
  vpc_id      = local.resolved_vpc_id

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project = "jarvis"
  }
}
