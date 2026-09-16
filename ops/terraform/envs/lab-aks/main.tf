module "cluster" {
  source = "../../modules/cluster-aks"

  resource_group_name    = var.resource_group_name
  location               = var.location
  cluster_name           = var.cluster_name
  dns_prefix             = var.dns_prefix
  kubernetes_version     = var.kubernetes_version
  node_count             = var.node_count
  vm_size                = var.vm_size
  create_acr             = var.create_acr
  acr_name               = var.acr_name
  ingress_class          = var.ingress_class
  storage_class          = var.storage_class
  enable_web_app_routing = var.enable_web_app_routing
}
