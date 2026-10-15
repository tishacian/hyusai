#!/usr/bin/env python3
"""Use the real PostgreSQL 17 client of the explicitly disposable local server."""
import os
import sys
if os.environ.get('PGHOST') != '127.0.0.1' or os.environ.get('PGPORT') != '15433':
    raise SystemExit('Only the disposable local test_obs_postgres endpoint is accepted')
os.execvp('docker', ['docker', 'exec', '-i', '-e', 'PGUSER', '-e', 'PGPASSWORD',
    '-e', 'PGHOST=127.0.0.1', '-e', 'PGPORT=5432', 'test_obs_postgres', 'psql', *sys.argv[1:]])
