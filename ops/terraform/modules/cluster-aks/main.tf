resource "azurerm_resource_group" "this" {
  name     = var.resource_group_name
  location = var.location
}

resource "azurerm_kubernetes_cluster" "this" {
  name                = var.cluster_name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  dns_prefix          = var.dns_prefix != "" ? var.dns_prefix : var.cluster_name
  kubernetes_version  = var.kubernetes_version

  default_node_pool {
    name       = "default"
    node_count = var.node_count
    vm_size    = var.vm_size
  }

  identity {
    type = "SystemAssigned"
  }

  dynamic "web_app_routing" {
    for_each = var.enable_web_app_routing ? [1] : []
    content {
      dns_zone_ids = []
    }
  }
}

resource "azurerm_container_registry" "this" {
  count               = var.create_acr ? 1 : 0
  name                = var.acr_name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = false
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  count                            = var.create_acr ? 1 : 0
  principal_id                     = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
  role_definition_name             = "AcrPull"
  scope                            = azurerm_container_registry.this[0].id
  skip_service_principal_aad_check = true
}
