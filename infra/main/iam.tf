# Permisos de datos para el Lambda de flight_price_check: leer rutas
# vigiladas, escribir precios, guardar la respuesta cruda de SerpApi en S3
# para poder debuggear cuando algo se rompa.
data "aws_iam_policy_document" "scraper_data_access" {
  statement {
    sid       = "ScanWatchedRoutes"
    actions   = ["dynamodb:Scan"]
    resources = [aws_dynamodb_table.watched_routes.arn]
  }

  statement {
    sid       = "WriteFlightPrices"
    actions   = ["dynamodb:PutItem"]
    resources = [aws_dynamodb_table.flight_prices.arn]
  }

  statement {
    sid       = "PutRawScrape"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.scrape_raw.arn}/*"]
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "flight_price_check_lambda" {
  name               = "${var.project_name}-flight-price-check-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "flight_price_check_lambda_data_access" {
  name   = "${var.project_name}-flight-price-check-lambda-data-access"
  role   = aws_iam_role.flight_price_check_lambda.id
  policy = data.aws_iam_policy_document.scraper_data_access.json
}

data "aws_iam_policy_document" "flight_price_check_lambda_extra" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.flight_price_check.arn}:*"]
  }

  statement {
    sid       = "ReadSerpApiSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.serpapi_api_key.arn]
  }
}

resource "aws_iam_role_policy" "flight_price_check_lambda_extra" {
  name   = "${var.project_name}-flight-price-check-lambda-extra"
  role   = aws_iam_role.flight_price_check_lambda.id
  policy = data.aws_iam_policy_document.flight_price_check_lambda_extra.json
}

resource "aws_iam_role" "price_alert_lambda" {
  name               = "${var.project_name}-price-alert-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "price_alert_lambda_permissions" {
  statement {
    sid = "ReadFlightPricesStream"
    actions = [
      "dynamodb:GetRecords",
      "dynamodb:GetShardIterator",
      "dynamodb:DescribeStream",
      "dynamodb:ListStreams",
    ]
    resources = [aws_dynamodb_table.flight_prices.stream_arn]
  }

  statement {
    sid       = "ReadWatchedRoutes"
    actions   = ["dynamodb:GetItem"]
    resources = [aws_dynamodb_table.watched_routes.arn]
  }

  statement {
    sid       = "SendAlertEmail"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = [aws_ses_email_identity.alert.arn]
  }
}

resource "aws_iam_role_policy" "price_alert_lambda_permissions" {
  name   = "${var.project_name}-price-alert-lambda-policy"
  role   = aws_iam_role.price_alert_lambda.id
  policy = data.aws_iam_policy_document.price_alert_lambda_permissions.json
}

data "aws_iam_policy_document" "price_alert_lambda_logs" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.price_alert.arn}:*"]
  }
}

resource "aws_iam_role_policy" "price_alert_lambda_logs" {
  name   = "${var.project_name}-price-alert-lambda-logs"
  role   = aws_iam_role.price_alert_lambda.id
  policy = data.aws_iam_policy_document.price_alert_lambda_logs.json
}

data "tls_certificate" "github" {
  url = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github.certificates[0].sha1_fingerprint]
}

data "aws_iam_policy_document" "github_actions_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy" {
  name               = "${var.project_name}-gha-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume.json
}

data "aws_iam_policy_document" "github_actions_deploy" {
  statement {
    sid = "LambdaDeploy"
    actions = [
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
      "lambda:GetFunction",
    ]
    resources = [
      aws_lambda_function.flight_price_check.arn,
      aws_lambda_function.price_alert.arn,
    ]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name   = "${var.project_name}-gha-deploy-policy"
  role   = aws_iam_role.github_actions_deploy.id
  policy = data.aws_iam_policy_document.github_actions_deploy.json
}
