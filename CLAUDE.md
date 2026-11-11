# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal DevOps lab, budget-capped at ~$20/month, that periodically checks flight prices for user-defined routes (e.g. Mendoza→Bariloche) across airlines and emails an alert when the best price found drops below a target. Infrastructure is OpenTofu (not Terraform CLI — use the `tofu` binary); comments/descriptions in the code are written in Spanish, match that when editing existing files.

**Current status (2026-08-25): active, validated end-to-end.** The first version queried each airline's website directly; neither offers a public API and both restrict automated access, so it was replaced with **SerpApi's `google_flights` engine** (an official, documented, paid API over Google Flights) — a single query already returns both airlines for a route. Validated live against the real API on 2026-08-25 (MDZ→BRC, real ARS prices, real DynamoDB write, real alert email delivered).

The old per-airline Lambdas and the VPC/ECS/ECR infra they needed are gone. One Lambda, `apps/flight_price_check/`, now handles both airlines.

**Note on infra history**: the previous incarnation of this infra was reported as "fully deployed and smoke-tested" in an earlier session, but by 2026-08-25 the OpenTofu state for `infra/main` was found completely empty (only the bootstrap S3/DynamoDB survived) — it had been destroyed at some point without this file being updated. **Don't trust status claims in git history at face value — verify with `tofu state list` or `aws lambda list-functions` before assuming anything is actually live.**

## Architecture

```
EventBridge Scheduler (1 schedule, rate(1 day) default)
        └──► Lambda flight-price-check (apps/flight_price_check/)
                        │  sweeps a grid of (outbound_date, return_date) pairs
                        │  per route against SerpApi's google_flights engine,
                        │  tracks cheapest overall + cheapest direct-if-any
                        ▼
        DynamoDB flight_prices (stream: NEW_IMAGE)
                        │
                        ▼
        Lambda price-alert → SES → email (HTML)   (apps/price_alert/)
```

`watched_routes` DynamoDB table (hash key `route_id`) holds `origin`/`destination`/`target_price`/`active`, plus optional per-route search-grid overrides: `search_window_days` (default 60), `stay_nights` (default 7), `date_step_days` (default 5). No VPC, no NAT Gateway, no ECS — everything is a plain Lambda making outbound HTTPS calls to `serpapi.com`.

## Structure — three separate OpenTofu roots

Each directory under `infra/` is an independent root module with its own state. Always `cd` into the specific directory before running `tofu` commands.

- **`infra/bootstrap/`** — Applied once, manually, with local state. Creates the S3 bucket + DynamoDB table the `infra/main` remote backend depends on. Already applied for this repo (backend values are in `infra/main/backend.tf`).
- **`infra/main/`** — The actual lab infrastructure: IAM (`iam.tf`), DynamoDB tables (`dynamodb.tf`), raw-response S3 landing zone (`s3.tf`), the SES identities for alerts (`ses.tf`), the SerpApi API key in Secrets Manager (`secrets.tf`), both Lambdas (`lambda.tf`), and the EventBridge Scheduler wiring (`scheduler.tf`). Exposes `ses_domain`/`ses_domain_verification_token`/`ses_domain_dkim_tokens` as outputs (`outputs.tf`) so `infra/cloudflare` can read them via remote state.
- **`infra/github/`** — Manages the GitHub repository resource itself, separate from AWS infra.
- **`infra/cloudflare/`** — Manages DNS + Email Routing for `rodrigo-riedel.ar` (local state, no backend — same pattern as `infra/github/`). Reads `infra/main`'s SES outputs via `data "terraform_remote_state" "main"` (points at the same S3 backend as `infra/main/backend.tf` — nothing is copy-pasted between the two roots) to create the SES domain-verification TXT + 3 DKIM CNAME records, plus the Email Routing destination address and forwarding rule (`alertas_precio@rodrigo-riedel.ar` → the real Gmail). **Apply order matters**: `infra/main` first (creates the SES domain identity + DKIM, instant, nothing to wait on) → `infra/cloudflare` (writes the actual DNS) → wait for propagation → `infra/main` again (now `aws_ses_domain_identity_verification` can find the TXT and confirm). See `ses.tf` for the full sequencing note.

## Application code — `apps/`

- **`apps/flight_price_check/handler.py`** — Lambda, stdlib-only (`urllib.request`) + `boto3` (already in the Lambda runtime, no build step). Each leg (outbound and return) is priced **independently as one-way** (`type=2`) and the total is the sum — not a bundled `type=1` round-trip fare — specifically so a single leg can be swapped for a cheaper/faster airline combination without breaking price consistency. For each active route, sweeps a fixed-step grid of candidate dates (not every single day — see `SEARCH_WINDOW_DAYS_DEFAULT`/`DATE_STEP_DAYS_DEFAULT`), 2 one-way calls per date pair (outbound + return), tracking cheapest overall and cheapest fully-direct (both legs nonstop — exact now, not an approximation). **Self-transfer combining**: once a winner date is picked, for each leg whose real layover exceeds `LAYOVER_THRESHOLD_MINUTES` (240/4h), searches nonstop+nonstop combinations of *any* airline via Buenos Aires (`HUBS = ["AEP", "EZE"]`) with a connection between `MIN_CONNECTION_MINUTES` (60) and the layover threshold, and swaps in the combo only if its price is ≤ the official leg's price. This only runs for the single winning date, not the whole sweep (cost control) — documented as an accepted trade-off in the file's docstring. A combo leg is marked `self_transfer: true` (separately-ticketed — no delay/reaccommodation protection between the two flights) so `price_alert` can flag it. Writes one `flight_prices` item per route per run with `outbound`/`return`, each holding `segments` (airline, flight number, times, duration), `layovers` (airport, duration), and `self_transfer`. Dumps every raw SerpApi response (sweep + any combo search) to S3 (`serpapi/{route_id}/{scraped_at}.json`) regardless of success, for debugging. Cost: worst case ~32 SerpApi calls/route/run (vs ~13 before combining was added) — still trivial against the $20/month ceiling (see below).
- **`apps/price_alert/handler.py`** — Lambda triggered by the `flight_prices` DynamoDB stream (batched: `batch_size=20`, `maximum_batching_window_in_seconds=30`, so multiple routes alerting in the same run land in one email instead of several). Compares each record against `watched_routes.target_price`, and for everything below target, sends **one HTML email via SES** (not SNS — SNS can't render HTML, only plain text) with a table per route (ordered route → airline → price) showing both legs' flights and layover durations. When a leg is `self_transfer` (separately-ticketed airline combo), adds a warning row about the lack of connection protection. Airline-agnostic — reads whatever fields are on the stream record. Validated end-to-end 2026-08-25 (real alert delivered, HTML table format confirmed by the user).

The SerpApi API key lives in Secrets Manager (`aws_secretsmanager_secret.serpapi_api_key`), never as a plain env var or in any tracked file — the Lambda fetches it once per warm execution environment via `secretsmanager:GetSecretValue`. SES has two identities: `aws_ses_email_identity.alert` (the recipient, `var.alert_email`, a Gmail address — still needed while SES is in sandbox, since the recipient must be verified) and `aws_ses_domain_identity.alert_domain` (the sender's domain, derived from `var.alert_from_email`, e.g. `alertas_precio@rodrigo-riedel.ar`) + its DKIM. Both being verified keeps everything inside the SES sandbox — no production access request needed.

## CI/CD — `.github/workflows/ci-cd.yml`

Single workflow, three jobs: `python` (ruff + pytest on `tests/`) and `tofu` (matrix over the 4 roots: `fmt -check` + `init -backend=false` + `validate`) run on every PR/push with no AWS credentials; `deploy` (matrix over both Lambdas) runs only on `main` (push or manual `workflow_dispatch`, never PRs) after both pass. Deploy assumes `aws_iam_role.github_actions_deploy` via OIDC (role ARN comes from the repo variable `AWS_DEPLOY_ROLE_ARN` = `tofu output -raw github_actions_deploy_role_arn`), builds a deterministic zip with `scripts/build_lambda_zip.py`, skips if it matches the live `CodeSha256`, else `update-function-code` + waits + verifies the hash.

- CI only deploys **Lambda code**. Infra changes still go through a manual `tofu apply` — the deploy role is deliberately scoped to `lambda:UpdateFunctionCode` + `lambda:GetFunction` on the two functions (it can't change config, env vars or IAM).
- The deploy job must NOT use `environment:` — that changes the OIDC `sub` claim to `repo:...:environment:<name>` and the trust policy (which only allows `ref:refs/heads/main`) would reject it.
- **Lambda code is owned by CI, config by OpenTofu.** Both `aws_lambda_function`s have `lifecycle { ignore_changes = [filename, source_code_hash] }`: `archive_file` only supplies the initial zip at creation; after that, code changes reach AWS only through the pipeline. To push code without CI (e.g. CI broken), build with `scripts/build_lambda_zip.py` and `aws lambda update-function-code` by hand — `tofu apply` will NOT do it.
- Tests load each `handler.py` by path under distinct module names (`tests/conftest.py`) because both files share the same name; env vars the handlers read at import time are set to dummies there.

## Commands

Run from within the relevant `infra/<dir>`:

```bash
tofu init
tofu plan
tofu apply
```

`infra/main` requires `-var="alert_email=..."`, `-var="github_repo=..."`, and `-var="serpapi_api_key=..."` (or a `terraform.tfvars`, gitignored — copy `terraform.tfvars.example`). The schedule starts `DISABLED` (`price_drop_check_enabled` var) — flip to `ENABLED` only after manually validating the pipeline end-to-end (see below).

### Managing watched routes (no redeploy needed)

```bash
aws dynamodb put-item --table-name devops-lab-watched-routes --item \
  '{"route_id":{"S":"MDZ-BRC"},"origin":{"S":"MDZ"},"destination":{"S":"BRC"},"target_price":{"N":"200000"},"active":{"BOOL":true}}'
```

Add `search_window_days`/`stay_nights`/`date_step_days` (all `N`) to the item to override the per-route search grid defaults.

### Manually testing (before enabling the schedule)

```bash
aws lambda invoke --function-name devops-lab-flight-price-check /dev/stdout
```

Can take several minutes (up to ~32 SerpApi calls sequentially per route: the date sweep plus any self-transfer combo search) — the Lambda timeout is 600s to give it room.

## Conventions

- **The repo is public.** No personal data in tracked files (real email addresses, account IDs, tokens) — those go in gitignored `terraform.tfvars`, which is why `forward_to_email` (`infra/cloudflare`) and `alert_email` (`infra/main`) have no defaults. Keep docs about past data sources neutral: describe *that* a source was dropped and why at a high level, not access-control specifics.

- Resource names/tags are prefixed with `var.project_name` (default `devops-lab`).
- `infra/main` sets `default_tags` (`Project`, `ManagedBy = "opentofu"`) at the provider level — don't re-add these tags per-resource.
- The SES email identity (recipient) needs a manual click-to-verify from the inbox after apply — Terraform can't complete that step.
- **Two `infra/cloudflare` resources are deliberately NOT in Terraform**, both documented in `email_routing.tf`: `cloudflare_email_routing_settings` hits a real provider bug in v5.24.0 (the latest at the time — schema mismatch on `support_subaddress`); `cloudflare_email_routing_dns` (the one that writes the MX/SPF records) 403s with a scoped API token no matter which permission combination gets tried (DNS/Email Routing Rules/Email Routing Addresses/Zone Settings, all at Edit) — root cause not found. Both were done once, manually, via the Cloudflare dashboard (**Email → Email Routing → Enable**) — if the zone/routing ever needs recreating, redo that click first, don't assume `tofu apply` covers it.
- SPF/DMARC records are out of scope on purpose — Cloudflare Email Routing and SES each want their own TXT at the domain apex, and declaring both blindly in Terraform risks clobbering one with the other. Revisit only if alerts start landing in spam.
- The GitHub Actions deploy IAM role trust policy restricts `sub` to `<prefix>:ref:refs/heads/main`, where `<prefix>` is `var.github_oidc_sub_prefix` if set, else `repo:${var.github_repo}`. The repo uses GitHub's **immutable OIDC subject** (`repo:owner@<owner_id>/repo@<repo_id>`, default for new repos) — the prefix comes from `gh api repos/<owner>/<repo>/actions/oidc/customization/sub` and **changes if the repo is ever deleted and recreated**; a mismatch shows up as `Not authorized to perform sts:AssumeRoleWithWebIdentity` in the deploy job — any new workflow triggers need a corresponding condition update in `infra/main/iam.tf`.
- `.gitignore` excludes `*.tfvars` except `terraform.tfvars.example` — keep the example file in sync with `variables.tf`.
- SerpApi Free plan: 250 searches/month, no card required. At the default daily-sweep schedule (~13-32 calls/route/day depending on how often self-transfer combos get searched), 1 route runs a few hundred calls/month over the free tier at $2/1000 — a dollar or two per route per month, trivial against the ~$20/month budget ceiling.
