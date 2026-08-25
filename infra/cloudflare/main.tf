# Root separado (mismo patron que infra/github/): estado local, sin backend
# remoto - no maneja nada tan critico como para justificar el mismo backend
# S3 que infra/main, y evita darle a este provider acceso al backend de AWS.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# Solo para leer el remote state de infra/main (bucket S3) - este root no
# crea ni administra ningun recurso de AWS.
provider "aws" {
  region = "us-east-1"
}
