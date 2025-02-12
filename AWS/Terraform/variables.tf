variable "aws_region" {
  description = "AWS region"
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  default     = "10.0.0.0/16"
}

variable "env" {
  description = "Environment name"
  default     = "Development"
}

variable "instance_type" {
  description = "EC2 instance type"
  default     = "t3.micro"
}

variable "instance_count" {
  description = "count of instance for ALB"
  default = 2
}