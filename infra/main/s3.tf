data "aws_caller_identity" "current" {}

# Landing zone del JSON crudo de cada respuesta de SerpApi, para poder
# debuggear si la API cambia de forma o empieza a fallar. (El nombre
# "scrape_raw" se mantiene para no forzar el reemplazo del bucket.)
resource "aws_s3_bucket" "scrape_raw" {
  bucket = "${var.project_name}-scrape-raw-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "scrape_raw" {
  bucket                  = aws_s3_bucket.scrape_raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "scrape_raw" {
  bucket = aws_s3_bucket.scrape_raw.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "scrape_raw" {
  bucket = aws_s3_bucket.scrape_raw.id

  rule {
    id     = "expire-raw-scrapes"
    status = "Enabled"

    filter {}

    expiration {
      days = 14
    }
  }
}
