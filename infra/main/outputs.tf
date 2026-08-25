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
