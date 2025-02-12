module "ec2_instances" {
  source  = "terraform-aws-modules/ec2-instance/aws"
  version = "5.7.1"

  name           = "Mention_Bot-app-instance"
  instance_count = 2

  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = module.vpc.public_subnets[0]
  vpc_security_group_ids = [module.ec2_security_group.security_group_id]
  associate_public_ip_address = true

  tags = {
    "Name"        = "Mention_Bot_Instance"
    "Environment" = var.env

  user_data = file("${path.module}/user_data.sh")
  }
}

module "mongo_instance" {
  source = "terraform-aws-modules/ec2-instance/aws"
  version = "5.7.1"

  name = "mongo_instance"

  ami = data.aws_ami.ubuntu.id
  instance_type = var.instance_type
  subnet_id = module.vpc.private_subnets[0]
  vpc_security_group_ids = [module.mongo_security_group.security_group_id]
  associate_public_ip_address = false

  tags = {
    "Name" = "MongoDB_Instance"
    "Environment" = var.env
  }

  user_data =file("${path.module}/user_data.sh")
}
