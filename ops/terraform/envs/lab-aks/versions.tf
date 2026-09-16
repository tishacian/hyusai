terraform {
  required_version = ">= 1.6.0"

  backend "http" {}

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.117"
    }
  }
}

provider "azurerm" {
  features {}
}
