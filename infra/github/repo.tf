resource "github_repository" "lab" {
  name        = var.repo_name
  description = "Lab DevOps en AWS: monitor de precios de vuelos con Lambda, DynamoDB y SES - OpenTofu + GitHub Actions (OIDC)"
  visibility  = var.repo_visibility
  topics      = ["aws", "opentofu", "github-actions", "serverless", "devops", "aws-lambda", "dynamodb", "infrastructure-as-code"]

  auto_init = false

  delete_branch_on_merge = true
  vulnerability_alerts   = true

  lifecycle {
    prevent_destroy = true
  }
}

# Protege main contra force-push y borrado (el historial ya se reescribio una
# vez a proposito para publicar el repo - que no vuelva a pasar por accidente).
# No exige PRs: es un repo de una sola persona y se pushea directo a main.
resource "github_repository_ruleset" "main" {
  name        = "protect-main"
  repository  = github_repository.lab.name
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true
  }
}

# PRs automaticos de Dependabot cuando una dependencia tiene una vulnerabilidad
# conocida (las alertas se activan con vulnerability_alerts en el repo).
resource "github_repository_dependabot_security_updates" "lab" {
  repository = github_repository.lab.name
  enabled    = true
}
