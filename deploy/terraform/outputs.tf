output "url" {
  description = "Open this once setup finishes (about 3-5 minutes after apply)."
  value       = "http://${aws_instance.checkflow.public_ip}${var.app_port == 80 ? "" : ":${var.app_port}"}"
}

output "admin_username" {
  value = "admin"
}

output "admin_password" {
  description = "Show with: terraform output -raw admin_password"
  value       = random_password.admin.result
  sensitive   = true
}

output "instance_id" {
  value = aws_instance.checkflow.id
}

output "ssm_shell" {
  description = "Interactive shell on the box (needs the Session Manager plugin on your computer)."
  value       = "aws ssm start-session --region ${var.region} --target ${aws_instance.checkflow.id}"
}

output "ssm_reinstall" {
  description = "Re-run the app install (latest commit) without a shell or the plugin. Check it with the ssm_reinstall_result command."
  value       = "aws ssm send-command --region ${var.region} --instance-ids ${aws_instance.checkflow.id} --document-name AWS-RunShellScript --parameters 'commands=[\"/usr/local/bin/checkflow-install\"]' --query Command.CommandId --output text"
}

output "ssm_reinstall_result" {
  value = "aws ssm get-command-invocation --region ${var.region} --instance-id ${aws_instance.checkflow.id} --command-id <id from ssm_reinstall>"
}

output "setup_log" {
  description = "Run on the box to watch the install."
  value       = "sudo tail -f /var/log/checkflow-setup.log"
}
