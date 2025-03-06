module "alb" {
  source  = "terraform-aws-modules/alb/aws"
  version = "9.13.0"

  name = "my-alb_mention"

  load_balancer_type = "application"
  vpc_id             = module.vpc.vpc_id
  subnets            = module.vpc.public_subnets
  security_groups    = module.alb_security_group.security_group_id



  target_groups = {
    default = {
      name_prefix      = "default-"
      backend_protocol = "HTTP"
      backend_port     = 80
      target_type      = "instance"
      health_check = {
        enabled             = true
        interval            = 30
        path                = "/"
        port                = 5000
        healthy_threshold   = 3
        unhealthy_threshold = 3
        timeout             = 5
        matcher             = "200"
      }
    }
  }

#   http_tcp_listeners = [{
#     port     = 80
#     protocol = "HTTP"
#     default_action = {
#       type             = "forward"
#       target_group_name = "default"
#     }
#   }]

  tags = {
    Environment = var.env
  }
}

resource "aws_lb_target_group_attachment" "example" {
  count = var.instance_count
  target_group_arn = module.alb.target_groups["default"].arn
  target_id        = module.ec2_instances[count.index].id
}