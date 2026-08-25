data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.project_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_permissions" {
  statement {
    sid       = "InvokeFlightPriceCheckLambda"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.flight_price_check.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_permissions" {
  name   = "${var.project_name}-scheduler-policy"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_permissions.json
}

resource "aws_scheduler_schedule" "flight_price_check" {
  name       = "${var.project_name}-flight-price-check"
  group_name = "default"
  state      = var.price_drop_check_enabled

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.scrape_schedule_expression

  target {
    arn      = aws_lambda_function.flight_price_check.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}
