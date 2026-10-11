# Generation 13 — failed validation

Three real-provider responses placed AgentLoop inputs_map at node level,
where the runtime does not consume it. The job failed after 191.97 seconds.
No proposal was applied. The last provider proposal is retained unchanged.

The validation error previously asked for a source binding without identifying
its full location. It now names config.inputs_map.objective and explicitly says
to move node.inputs_map into config.inputs_map. The existing intervention
regression now exercises exactly this invalid shape. This improves repair
feedback without normalizing or silently accepting an invalid Flow.
