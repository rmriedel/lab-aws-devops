# TXT de verificacion de dominio para SES - el valor sale del remote state de
# infra/main (aws_ses_domain_identity.alert_domain.verification_token).
resource "cloudflare_dns_record" "ses_verification" {
  zone_id = data.cloudflare_zone.this.zone_id
  name    = "_amazonses.${var.domain}"
  type    = "TXT"
  content = data.terraform_remote_state.main.outputs.ses_domain_verification_token
  ttl     = 300
}

# 3 CNAME de DKIM para SES - mismo origen, uno por cada token.
resource "cloudflare_dns_record" "ses_dkim" {
  count   = length(data.terraform_remote_state.main.outputs.ses_domain_dkim_tokens)
  zone_id = data.cloudflare_zone.this.zone_id
  name    = "${data.terraform_remote_state.main.outputs.ses_domain_dkim_tokens[count.index]}._domainkey.${var.domain}"
  type    = "CNAME"
  content = "${data.terraform_remote_state.main.outputs.ses_domain_dkim_tokens[count.index]}.dkim.amazonses.com"
  ttl     = 300
}
