# Single-node OpenBao for the Agentium VM (compose.agentium.openbao.yml).
# Reachable only on agentium-net; nothing is published on the host.

ui            = false
# Integrated storage memory-maps its database; mlock is not recommended with raft.
disable_mlock = true
api_addr      = "http://agentium-openbao:8200"
cluster_addr  = "http://agentium-openbao:8201"

storage "raft" {
  path    = "/openbao/data/raft"
  node_id = "agentium-openbao-1"
}

listener "tcp" {
  address         = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  # Internal Docker network only; TLS terminates nowhere else on this path.
  tls_disable     = true
}

# Static-key auto-unseal (OpenBao >= 2.4). The 32-byte hex key is written by
# scripts/agentium_openbao_bootstrap.py prepare, mode 0400, outside the raft dir.
seal "static" {
  current_key_id = "agentium-1"
  current_key    = "file:///run/openbao-seal/unseal.key"
}

# API-created audit devices are disabled by default; declare it here instead.
audit "file" "agentium-file" {
  description = "Agentium audit log"
  options {
    file_path = "/openbao/data/audit/audit.log"
    mode      = "0600"
  }
}
