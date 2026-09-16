# module `cluster-ovh-mks`

Creates an OVH Managed Kubernetes cluster and one node pool.

Outputs match the portable contract (`kubeconfig`, `ingress_class`,
`storage_class`, `cluster_name`). The Load Balancer for the API is provided
by MKS; this module does not allocate a Nova floating IP.

Provider credentials are environment variables (`OVH_ENDPOINT`,
`OVH_APPLICATION_KEY`, `OVH_APPLICATION_SECRET`, `OVH_CONSUMER_KEY`).
The Public Cloud project id is `service_name`.
