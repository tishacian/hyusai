# Canonical generation worker qualification

The worker ran locally against an isolated database, with only the model call
routed through the existing Showcase provider on the VM. It completed on its
first attempt (59.45 seconds for pytest). Therefore this is evidence for the
real generation path, not a exercised real-provider repair cycle.

Applying the retained proposal succeeded, but its first draft Run was refused
by ingress validation: case input_ref contained `node_id`, which is not allowed
by the source's additionalProperties=false contract. No LLM execution occurred.
The cases are retained unchanged. Proposal validation now uses the canonical
JSON Schema validator to reject this mismatch before retention.

The worker evidence's model_execution label `remote-workspace-resolved` is a
local boundary placeholder, not the actual model identity. Provider output
retains its model field. The recorder has been corrected to retain the remote
resolver's public execution metadata on subsequent calls.

No live deployment, publication, human review or passing business suite is
claimed. The earlier recorder indentation failure occurred before provider use
and is not counted as a generation attempt.
