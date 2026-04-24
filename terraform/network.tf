locals {
  use_default_vpc = var.vpc_id == "default"
}

data "aws_vpc" "default" {
  count   = local.use_default_vpc ? 1 : 0
  default = true
}

data "aws_vpc" "named" {
  count = local.use_default_vpc ? 0 : 1
  id    = var.vpc_id
}

locals {
  resolved_vpc_id = local.use_default_vpc ? data.aws_vpc.default[0].id : data.aws_vpc.named[0].id
}

data "aws_subnets" "task" {
  filter {
    name   = "vpc-id"
    values = [local.resolved_vpc_id]
  }
}

locals {
  subnet_ids = data.aws_subnets.task.ids
}
