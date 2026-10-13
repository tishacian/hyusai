"""DataOps: tabular transforms run where the data size says they should.

The engine is the standalone DuckDB runner (``resources/dataops_runner.py``);
this package decides where it runs and settles what it produced. Today the one
placement is the worker plane (a supervised subprocess on the ``dataops``
queue); ephemeral pods and Spark applications are later placements of the same
contract — a manifest in, a Parquet file and a summary out.
"""
