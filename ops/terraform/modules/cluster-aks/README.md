# module `cluster-aks`

Creates a resource group, an AKS cluster, and optionally an ACR with
`AcrPull` for the kubelet identity.

Outputs match the portable contract (`kubeconfig`, `ingress_class`,
`storage_class`, `cluster_name`). Default ingress class is Azure Application
Routing; set `ingress_class = "nginx"` when ingress-nginx is installed
instead.

Realtime (LiveKit, `docs/ops/agentium-kubernetes.md`), both off by default:
`livekit_public_ip` reserves the static IP `<cluster_name>-livekit` in the
node resource group for the chart's `loadBalancer` mode (output
`livekit_public_ip`); `media_node_pool` adds a pool with public node IPs,
the UDP range and RTC TCP port allowed as host ports, labelled and tainted
`agentium.io/media=livekit`, for the `hostNetwork` mode.

Provider credentials are the usual `ARM_*` environment variables.
