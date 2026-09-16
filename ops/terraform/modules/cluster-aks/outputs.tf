output "kubeconfig" {
  description = "Admin kubeconfig for Ansible / helm upgrade."
  value       = azurerm_kubernetes_cluster.this.kube_config_raw
  sensitive   = true
}

output "ingress_class" {
  value = var.ingress_class
}

output "storage_class" {
  value = var.storage_class
}

output "cluster_name" {
  value = azurerm_kubernetes_cluster.this.name
}

output "cluster_id" {
  value = azurerm_kubernetes_cluster.this.id
}

output "acr_login_server" {
  value = var.create_acr ? azurerm_container_registry.this[0].login_server : ""
}
