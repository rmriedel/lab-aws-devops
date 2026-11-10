# Consumidos por infra/cloudflare via terraform_remote_state - asi el TXT de
# verificacion y los CNAME de DKIM no se copian a mano entre los dos roots.
output "ses_domain" {
  value = aws_ses_domain_identity.alert_domain.domain
}

output "ses_domain_verification_token" {
  value = aws_ses_domain_identity.alert_domain.verification_token
}

output "ses_domain_dkim_tokens" {
  value = aws_ses_domain_dkim.alert_domain.dkim_tokens
}

# Va como variable de repo AWS_DEPLOY_ROLE_ARN en GitHub - la usa el job
# deploy de .github/workflows/ci-cd.yml para asumir el rol via OIDC.
output "github_actions_deploy_role_arn" {
  value = aws_iam_role.github_actions_deploy.arn
}
