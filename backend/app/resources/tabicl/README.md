# TabICL redistribution notice

`LICENSE` is the complete, unmodified upstream notice at the source revision
recorded in `provenance.json`. Its SHA-256 is verified before packaging or
admitting a TabICL snapshot. The same provenance records the immutable model card
declaring BSD-3-Clause for the official weights. No network lookup occurs at
packaging, activation, training or prediction time.

The tabular code and weights permit use, modification and redistribution,
including commercial use, under BSD-3-Clause: preserve the copyright, conditions
and disclaimer, and do not imply endorsement. The upstream package also ships
the forecast module's Apache-2.0 notice; it is retained intact even though that
module is outside this pilot's functional scope.

`package_tabicl_bundle.py` writes the complete notice and provenance into
`license.json` and includes it in the signed file inventory. The existing
ObjectStore import, worker snapshot copy and autonomous model export then carry
the same bytes with the weights. No additional storage backend is introduced.

An older bundle without this file may remain stored for history, but cannot be
activated or used to create a new training export. Repackage its original
converted weights with this notice, import the resulting new immutable artifact
through the existing workspace authorization flow, and activate that artifact.
Do not alter an existing signed manifest or an already published model in place.
