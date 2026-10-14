data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"] # Python 3.12
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

data "aws_vpc" "default" {
  default = true
}

# Replaces the stock admin/admin so the demo is never open with the default password.
resource "random_password" "admin" {
  length  = 16
  special = false
}

resource "aws_security_group" "checkflow" {
  name_prefix = "checkflow-demo-"
  description = "CheckFlow demo"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "CheckFlow web UI"
    from_port   = var.app_port
    to_port     = var.app_port
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  dynamic "ingress" {
    for_each = var.key_name == null || length(var.ssh_cidrs) == 0 ? [] : [1]
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = var.ssh_cidrs
    }
  }

  egress {
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Shell access through AWS Session Manager, so port 22 can stay closed.
resource "aws_iam_role" "checkflow" {
  name_prefix = "checkflow-demo-"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "ec2.amazonaws.com" } }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.checkflow.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "checkflow" {
  name_prefix = "checkflow-demo-"
  role        = aws_iam_role.checkflow.name
}

resource "aws_instance" "checkflow" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  key_name                    = var.key_name
  vpc_security_group_ids      = [aws_security_group.checkflow.id]
  iam_instance_profile        = aws_iam_instance_profile.checkflow.name
  associate_public_ip_address = true

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url       = var.repo_url
    git_ref        = var.git_ref
    app_port       = var.app_port
    admin_password = random_password.admin.result
  })
  user_data_replace_on_change = true

  metadata_options {
    http_tokens = "required" # IMDSv2 only
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "checkflow-demo" }
}
