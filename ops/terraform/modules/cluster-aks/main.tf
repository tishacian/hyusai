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

# LiveKit media nodes (Helm livekit.network.mode=hostNetwork). AKS nodes have
# no public address and the managed NSG drops host ports unless the pool
# allows them.
resource "azurerm_kubernetes_cluster_node_pool" "media" {
  count = var.media_node_pool.enabled ? 1 : 0

  name                  = var.media_node_pool.name
  kubernetes_cluster_id = azurerm_kubernetes_cluster.this.id
  vm_size               = var.media_node_pool.vm_size
  node_count            = var.media_node_pool.node_count
  enable_node_public_ip = true
  node_labels = {
    "agentium.io/media" = "livekit"
  }
  node_taints = ["agentium.io/media=livekit:NoSchedule"]

  node_network_profile {
    allowed_host_ports {
      port_start = var.media_node_pool.udp_port_start
      port_end   = var.media_node_pool.udp_port_end
      protocol   = "UDP"
    }
    allowed_host_ports {
      port_start = var.media_node_pool.rtc_tcp_port
      port_end   = var.media_node_pool.rtc_tcp_port
      protocol   = "TCP"
    }
  }
}

# Static address for Helm livekit.network.mode=loadBalancer. In the node
# resource group, where the cluster identity may attach it to its LoadBalancer.
resource "azurerm_public_ip" "livekit" {
  count = var.livekit_public_ip ? 1 : 0

  name                = "${var.cluster_name}-livekit"
  resource_group_name = azurerm_kubernetes_cluster.this.node_resource_group
  location            = azurerm_resource_group.this.location
  allocation_method   = "Static"
  sku                 = "Standard"
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
