output "kubeconfig" {
  description = "Admin kubeconfig for the lab AKS cluster."
  value       = module.cluster.kubeconfig
  sensitive   = true
}

output "ingress_class" {
  value = module.cluster.ingress_class
}

output "storage_class" {
  value = module.cluster.storage_class
}

output "cluster_name" {
  value = module.cluster.cluster_name
}

output "cluster_id" {
  value = module.cluster.cluster_id
}

output "acr_login_server" {
  value = module.cluster.acr_login_server
}
