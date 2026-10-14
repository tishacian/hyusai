import json
import resource
import threading
import time
from pathlib import Path

root = Path('/sys/fs/cgroup')
limits = {name: (root / name).read_text().strip() for name in ('memory.max', 'memory.swap.max', 'cpu.max')}
assert limits == {'memory.max': '201326592', 'memory.swap.max': '0', 'cpu.max': '50000 100000'}, limits
try:
    Path('/proc/self/oom_score_adj').write_text('1000')
except OSError:
    pass
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_CPU, (10, 12))
import duckdb

conn = duckdb.connect(config={'memory_limit': '16MB', 'threads': 1})
conn.execute("SET temp_directory=''")
conn.execute('SET enable_external_access=false')
conn.execute('SET lock_configuration=true')
sql = "CREATE TEMP TABLE __preview_output AS SELECT lpad('x',1000000000,'x') AS text FROM (VALUES (1)) AS sample(id)"
print(json.dumps({'duckdb': duckdb.__version__, 'sql': sql, 'limits': limits, 'duckdb_memory_limit': '16MB', 'threads': 1, 'interrupt_after_s': 5}), flush=True)
timer = threading.Timer(5, conn.interrupt)
timer.daemon = True
started = time.monotonic()
timer.start()
try:
    conn.execute(sql)
    print(json.dumps({'result': 'success', 'length': conn.execute('SELECT length(text) FROM __preview_output').fetchone()[0]}), flush=True)
except duckdb.Error as exc:
    print(json.dumps({'result': 'duckdb_exception', 'type': type(exc).__name__, 'message': str(exc)[:1000]}), flush=True)
finally:
    timer.cancel()
    conn.close()
    print(json.dumps({'seconds': time.monotonic() - started, 'maxrss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}), flush=True)
