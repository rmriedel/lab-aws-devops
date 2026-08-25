# Lee los outputs de SES (verification token + DKIM tokens) del state de
# infra/main - mismo bucket/backend que infra/main/backend.tf, asi no hay que
# copiar esos valores a mano entre los dos roots.
data "terraform_remote_state" "main" {
  backend = "s3"
  config = {
    bucket = "devops-lab-tfstate-77a2fab0"
    key    = "main/terraform.tfstate"
    region = "us-east-1"
  }
}

data "cloudflare_zone" "this" {
  filter = {
    name = var.domain
  }
}
