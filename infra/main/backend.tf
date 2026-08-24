terraform {
  required_version = ">= 1.6.0"

  backend "s3" {
    bucket         = "devops-lab-tfstate-77a2fab0"
    key            = "main/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "devops-lab-tfstate-lock"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
