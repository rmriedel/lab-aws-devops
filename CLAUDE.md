# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal DevOps lab, budget-capped at ~$20/month, that periodically checks flight prices for user-defined routes (e.g. Mendoza→Bariloche) across airlines and emails an alert when the best price found drops below a target. Infrastructure is OpenTofu (not Terraform CLI — use the `tofu` binary); comments/descriptions in the code are written in Spanish, match that when editing existing files.

**Current status (2026-08-25): active, validated end-to-end.** The first version queried each airline's website directly; neither offers a public API and both restrict automated access, so it was replaced with **SerpApi's `google_flights` engine** (an official, documented, paid API over Google Flights) — a single query already returns both airlines for a route. Validated live against the real API on 2026-08-25 (MDZ→BRC, real ARS prices, real DynamoDB write, real SNS email delivered).

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
        Lambda price-alert → SNS → email   (apps/price_alert/)
```

`watched_routes` DynamoDB table (hash key `route_id`) holds `origin`/`destination`/`target_price`/`active`, plus optional per-route search-grid overrides: `search_window_days` (default 60), `stay_nights` (default 7), `date_step_days` (default 5). No VPC, no NAT Gateway, no ECS — everything is a plain Lambda making outbound HTTPS calls to `serpapi.com`.

## Structure — three separate OpenTofu roots

Each directory under `infra/` is an independent root module with its own state. Always `cd` into the specific directory before running `tofu` commands.

- **`infra/bootstrap/`** — Applied once, manually, with local state. Creates the S3 bucket + DynamoDB table the `infra/main` remote backend depends on. Already applied for this repo (backend values are in `infra/main/backend.tf`).
- **`infra/main/`** — The actual lab infrastructure: IAM (`iam.tf`), DynamoDB tables (`dynamodb.tf`), raw-response S3 landing zone (`s3.tf`), SNS alerts topic (`sns.tf`), the SerpApi API key in Secrets Manager (`secrets.tf`), both Lambdas (`lambda.tf`), and the EventBridge Scheduler wiring (`scheduler.tf`).
- **`infra/github/`** — Manages the GitHub repository resource itself, separate from AWS infra.

## Application code — `apps/`

- **`apps/flight_price_check/handler.py`** — Lambda, stdlib-only (`urllib.request`) + `boto3` (already in the Lambda runtime, no build step). For each active route, sweeps a fixed-step grid of candidate outbound dates (not every single day — see `SEARCH_WINDOW_DAYS_DEFAULT`/`DATE_STEP_DAYS_DEFAULT` at the top of the file), one `type=1` (round trip) SerpApi call per date pair, and tracks the cheapest itinerary overall plus the cheapest one whose outbound leg is nonstop (`is_direct`). Writes one `flight_prices` item per route per run with the winner. Dumps every raw SerpApi response from the sweep to S3 (`serpapi/{route_id}/{scraped_at}.json`) regardless of success, for debugging. **Known simplification**: "directo" is judged from the outbound leg only (checking the return leg would require a second SerpApi call via `departure_token`, which isn't needed since the first call's `price` is already the full round-trip total) — documented in the file's docstring, not a bug.
- **`apps/price_alert/handler.py`** — Lambda triggered by the `flight_prices` DynamoDB stream, compares against `watched_routes.target_price`, publishes to SNS. Airline-agnostic — reads whatever `airline`/`price`/`currency`/`outbound_date`/`return_date`/`stops`/`is_direct` fields are on the stream record. Validated end-to-end 2026-08-25 (real alert delivered by email).

The SerpApi API key lives in Secrets Manager (`aws_secretsmanager_secret.serpapi_api_key`), never as a plain env var or in any tracked file — the Lambda fetches it once per warm execution environment via `secretsmanager:GetSecretValue`.

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

Takes ~1-2 minutes (sweeps ~12 SerpApi calls sequentially per route) — the Lambda timeout is 300s to give it room.

## Conventions

- Resource names/tags are prefixed with `var.project_name` (default `devops-lab`).
- `infra/main` sets `default_tags` (`Project`, `ManagedBy = "opentofu"`) at the provider level — don't re-add these tags per-resource.
- SNS email subscriptions need a manual click-to-confirm from the inbox after apply — Terraform can't complete that step.
- The GitHub Actions deploy IAM role trust policy restricts `sub` to `repo:${var.github_repo}:ref:refs/heads/main` — any new workflow triggers need a corresponding condition update in `infra/main/iam.tf`.
- `.gitignore` excludes `*.tfvars` except `terraform.tfvars.example` — keep the example file in sync with `variables.tf`.
- SerpApi Free plan: 250 searches/month, no card required. At the default daily-sweep schedule (~12 calls/route/day), 1 route stays within the free tier; each additional route adds a few hundred calls/month at $2/1000 — trivial against the ~$20/month budget ceiling.
