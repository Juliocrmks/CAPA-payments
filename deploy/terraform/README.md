# Demo on AWS EC2

One Ubuntu 24.04 box running CheckFlow on port 80, open to anyone (sign-in needs the generated admin password).
Shell access is through AWS Session Manager, so no SSH port or key is needed.

## Tools on your Mac (once)

```
brew install awscli
brew install --cask session-manager-plugin
brew tap hashicorp/tap && brew install hashicorp/tap/terraform
```

Then put your temporary credentials in the terminal (`export AWS_ACCESS_KEY_ID=… AWS_SECRET_ACCESS_KEY=…
AWS_SESSION_TOKEN=…`) and check them with `aws sts get-caller-identity`.

## Deploy

```
cd deploy/terraform
terraform init
terraform apply
terraform output -raw admin_password      # sign in as admin with this
```

Open the `url` output after 3-5 minutes (the box installs Python packages on first boot).

## Get onto the box

* `terraform output -raw ssm_shell` prints the command for a shell, then `sudo tail -f /var/log/checkflow-setup.log`.
  The SSM agent is started before the app install, so this works even if the install failed.
* **Install or update the app** (pulls the latest commit, keeps the database): `sudo checkflow-install` on the box, or
  without a shell or the plugin, run the `ssm_reinstall` output command.
* Service: `sudo systemctl status checkflow` · logs: `sudo journalctl -u checkflow -f`.

## Notes

* **Data**: it starts on the practice workbook. Use sample or redacted scans. Real packets carry account numbers
  and card photos, and this box is plain HTTP and open to the internet.
* **Cost**: a t3.medium is about $0.04/hour plus a 20 GB disk. `terraform destroy` when the demo is over.
* Needs a default VPC in the region, and credentials that can create EC2 instances, security groups and IAM roles.
