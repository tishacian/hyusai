resource "openstack_networking_network_v2" "cluster" {
  name           = "${var.name}-net"
  admin_state_up = true
}

resource "openstack_networking_subnet_v2" "cluster" {
  name            = "${var.name}-subnet"
  network_id      = openstack_networking_network_v2.cluster.id
  cidr            = var.cidr
  ip_version      = 4
  dns_nameservers = var.dns_nameservers
}

resource "openstack_networking_router_v2" "cluster" {
  name                = "${var.name}-router"
  admin_state_up      = true
  external_network_id = var.external_network_id
}

resource "openstack_networking_router_interface_v2" "cluster" {
  router_id = openstack_networking_router_v2.cluster.id
  subnet_id = openstack_networking_subnet_v2.cluster.id
}

resource "openstack_networking_floatingip_v2" "control_plane" {
  count = var.control_plane_count
  pool  = data.openstack_networking_network_v2.external.name
}

data "openstack_networking_network_v2" "external" {
  network_id = var.external_network_id
}
