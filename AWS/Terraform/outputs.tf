output "mongo_private_ip" {
  value = ec2_instances.mongo_instance.private_ip
}

output "bot_private_ip" {
  value = aws_instance.bot.private_ip
}

output "bastion_public_ip" {
  value = aws_instance.bastion.public_ip
}

output "jenkins_public_ip" {
  value = aws_instance.jenkins.public_ip
}
