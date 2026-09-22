terraform {
  required_version = ">= 1.6.0"

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 1.54"
    }
  }

  # Same GitLab HTTP backend as the managed-cluster envs, for the same
  # reason: it locks. Local state here would be the one unlocked state in
  # the repo, and this path creates volumes that hold data.
  # Init with ops/scripts/gitlab-tf-init.sh, or -backend-config=backend.hcl.
  backend "http" {}
}

provider "openstack" {
  auth_url    = var.os_auth_url
  region      = var.os_region
  tenant_name = var.os_tenant_name
  user_name   = var.os_username
  password    = var.os_password
  insecure    = var.os_insecure
}
