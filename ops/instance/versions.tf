terraform {
  required_version = ">= 1.6.0"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 1.54"
    }
  }

  # Remote state is an environment decision. Lab can stay local.
  # backend "http" {}
}

provider "openstack" {
  auth_url    = var.os_auth_url
  region      = var.os_region
  tenant_name = var.os_tenant_name
  user_name   = var.os_username
  password    = var.os_password
  insecure    = var.os_insecure
}
