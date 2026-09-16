terraform {
  required_version = ">= 1.6.0"

  backend "http" {}

  required_providers {
    ovh = {
      source  = "ovh/ovh"
      version = "~> 2.4"
    }
  }
}

provider "ovh" {
  # OVH_ENDPOINT, OVH_APPLICATION_KEY, OVH_APPLICATION_SECRET,
  # OVH_CONSUMER_KEY come from the environment (GitLab protected vars).
}
