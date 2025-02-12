module "ec2_security_group" {
  source  = "terraform-aws-modules/security-group/aws"
  version = "5.3.0"

  name        = "ec2-security-group_mention"
  description = "Security group for EC2 instances"
  vpc_id      = module.vpc.vpc_id

  ingress_cidr_blocks = ["10.0.0.0/16"] # Adjust as necessary
  ingress_rules       = ["all-all"]
  egress_rules        = ["all-all"]
}

module "alb_security_group" {
  source  = "terraform-aws-modules/security-group/aws"
  version = "5.3.0"

  name        = "alb-security-group"
  description = "Security group for ALB"
  vpc_id      = module.vpc.vpc_id

  ingress_cidr_blocks = ["0.0.0.0/0"]   # Adjust as necessary for your use case
     ingress_rules = ["http-80-tcp", "https-443-tcp"]
     egress_rules = ["all-all"]
}

module "mongo_security_group" {
  source  = "terraform-aws-modules/security-group/aws"
  version = "5.3.0"

  name        = "mongo-security-group"
  description = "Security group for MongoDB"
  vpc_id      = module.vpc.vpc_id

  ingress_cidr_blocks = ["0.0.0.0/0"]   # Adjust as necessary for your use case
     ingress_rules = ["http-22-tcp", "http-27017-tcp"]
     egress_rules = ["all-all"]
}