output "state_bucket_name" {
  description = "Pegar este valor en infra/main/backend.tf"
  value       = aws_s3_bucket.tf_state.bucket
}

output "lock_table_name" {
  description = "Pegar este valor en infra/main/backend.tf"
  value       = aws_dynamodb_table.tf_lock.name
}
