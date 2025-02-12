module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "5.18.1"

  name = "MyVPC_MentionBot"
  cidr = var.vpc_cidr

  azs             = ["us-east-1a", "us-east-1b", "us-east-1c"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24", "10.0.103.0/24"]
  private_subnets = ["10.0.104.0/24"]
  enable_nat_gateway      = true
  enable_vpn_gateway      = false
  map_public_ip_on_launch = true
  enable_dns_hostnames    = true

  tags = {
    "Environment" = var.env
  }
}