locals {
  use_explicit_subnets = length(var.subnet_ids) > 0
  use_default_vpc      = var.vpc_id == "default"
}

data "aws_vpc" "default" {
  count   = !local.use_explicit_subnets && local.use_default_vpc ? 1 : 0
  default = true
}

data "aws_vpc" "named" {
  count = !local.use_explicit_subnets && !local.use_default_vpc ? 1 : 0
  id    = var.vpc_id
}

locals {
  # When subnet_ids are explicit we still need a VPC ID for the security group.
  resolved_vpc_id = (
    local.use_explicit_subnets ? var.vpc_id :
    local.use_default_vpc ? data.aws_vpc.default[0].id :
    data.aws_vpc.named[0].id
  )
}

data "aws_subnets" "task" {
  count = local.use_explicit_subnets ? 0 : 1
  filter {
    name   = "vpc-id"
    values = [local.resolved_vpc_id]
  }
}

locals {
  subnet_ids = local.use_explicit_subnets ? var.subnet_ids : data.aws_subnets.task[0].ids
}
