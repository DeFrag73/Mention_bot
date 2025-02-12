provider "aws" {
  region = var.aws_region
}

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}



# resource "aws_security_group" "mongo_sg" {
#   vpc_id = module.vpc.vpc_id
#   name   = "mongo-sg"
#
#   ingress {
#     from_port   = 27017
#     to_port     = 27017
#     protocol    = "tcp"
#     cidr_blocks = ["0.0.0.0/0"]
#   }
#   egress {
#     from_port   = 0
#     to_port     = 0
#     protocol    = "-1"
#     cidr_blocks = ["0.0.0.0/0"]
#   }
# }
#
# resource "aws_instance" "mongo" {
#   ami                    = data.aws_ami.ubuntu.id
#   instance_type          = var.instance_type
#   subnet_id              = module.vpc.private_subnet_ids[0]
#   security_groups        = [aws_security_group.mongo_sg.name]
#   associate_public_ip_address = false
#   tags = {
#     Name = "mongo-${var.env}"
#   }
# }
#
# resource "aws_instance" "bot" {
#   ami                    = data.aws_ami.ubuntu.id
#   instance_type          = var.instance_type
#   subnet_id              = module.vpc.public_subnet_ids[0]
#   associate_public_ip_address = false
#   tags = {
#     Name = "bot-${var.env}"
#   }
# }
#
# resource "aws_instance" "bastion" {
#   ami                    = data.aws_ami.ubuntu.id
#   instance_type          = var.instance_type
#   subnet_id              = module.vpc.public_subnet_ids[0]
#   associate_public_ip_address = true
#   tags = {
#     Name = "bastion-${var.env}"
#   }
# }
#
# resource "aws_instance" "jenkins" {
#   ami                    = data.aws_ami.ubuntu.id
#   instance_type          = var.instance_type
#   subnet_id              = module.vpc.public_subnet_ids[1]
#   associate_public_ip_address = true
#   tags = {
#     Name = "jenkins-${var.env}"
#   }
# }