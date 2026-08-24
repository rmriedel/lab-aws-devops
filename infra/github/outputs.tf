output "clone_url_ssh" {
  value = github_repository.lab.ssh_clone_url
}

output "clone_url_https" {
  value = github_repository.lab.http_clone_url
}

output "repo_html_url" {
  value = github_repository.lab.html_url
}
