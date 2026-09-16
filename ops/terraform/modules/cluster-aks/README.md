# module `cluster-aks`

Creates a resource group, an AKS cluster, and optionally an ACR with
`AcrPull` for the kubelet identity.

Outputs match the portable contract (`kubeconfig`, `ingress_class`,
`storage_class`, `cluster_name`). Default ingress class is Azure Application
Routing; set `ingress_class = "nginx"` when ingress-nginx is installed
instead.

Provider credentials are the usual `ARM_*` environment variables.
