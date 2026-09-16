output "kubeconfig" {
  description = "Admin kubeconfig for Ansible / helm upgrade."
  value       = ovh_cloud_project_kube.this.kubeconfig
  sensitive   = true
}

output "ingress_class" {
  value = var.ingress_class
}

output "storage_class" {
  value = var.storage_class
}

output "cluster_name" {
  value = ovh_cloud_project_kube.this.name
}

output "cluster_id" {
  value = ovh_cloud_project_kube.this.id
}

output "nodepool_id" {
  value = ovh_cloud_project_kube_nodepool.default.id
}
