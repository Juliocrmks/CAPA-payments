variable "region" {
  description = "AWS region for the demo box."
  type        = string
  default     = "us-east-2"
}

variable "allowed_cidrs" {
  description = "Who may open the web UI. Default: anyone (sign-in still needs the generated admin password). Narrow it to e.g. [\"203.0.113.10/32\"] if you like."
  type        = list(string)
  default     = ["0.0.0.0/0"]
  validation {
    condition     = length(var.allowed_cidrs) > 0
    error_message = "Give at least one CIDR, e.g. [\"0.0.0.0/0\"]."
  }
}

variable "instance_type" {
  description = "4 GB of RAM is comfortable for the OCR models."
  type        = string
  default     = "t3.medium"
}

variable "app_port" {
  description = "Port the app listens on. 80 gives a clean http://<ip> URL."
  type        = number
  default     = 80
}

variable "repo_url" {
  description = "Git URL to clone. For a private repo use https://<token>@github.com/... (the token ends up in instance user data)."
  type        = string
  default     = "https://github.com/Juliocrmks/CAPA-payments.git"
}

variable "git_ref" {
  description = "Branch or tag to deploy."
  type        = string
  default     = "main"
}

variable "key_name" {
  description = "Optional EC2 key pair name to also allow SSH (from ssh_cidrs). Not needed: Session Manager works without it."
  type        = string
  default     = null
}

variable "ssh_cidrs" {
  description = "Where SSH is allowed from when key_name is set, e.g. [\"203.0.113.10/32\"]. Empty = no SSH port."
  type        = list(string)
  default     = []
}
