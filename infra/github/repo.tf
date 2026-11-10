resource "github_repository" "lab" {
  name        = var.repo_name
  description = "Lab DevOps en AWS: monitor de precios de vuelos con Lambda, DynamoDB y SES - OpenTofu + GitHub Actions (OIDC)"
  visibility  = var.repo_visibility
  topics      = ["aws", "opentofu", "github-actions", "serverless", "devops", "aws-lambda", "dynamodb", "infrastructure-as-code"]

  auto_init = false

  delete_branch_on_merge = true

  lifecycle {
    prevent_destroy = true
  }
}

#resource "github_branch_protection" "main" {
#  repository_id = github_repository.lab.node_id
#  pattern       = "main"
#
#  required_status_checks {
#    strict   = true
#    contexts = ["plan"]
#  }
#
#  enforce_admins = false
#}
