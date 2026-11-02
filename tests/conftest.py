"""A throwaway Postgres cluster with the Supabase roles, migrated fresh for each test."""
import os
import shutil
import socket
import subprocess
from pathlib import Path

import psycopg
import pytest

from load_supabase import apply_migration

PG_BIN = Path(os.environ.get("PG_BIN", "/opt/homebrew/opt/postgresql@15/bin"))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def pg_url(tmp_path_factory):
    if not (PG_BIN / "initdb").exists():
        pytest.skip(f"no Postgres binaries at {PG_BIN}")
    data = tmp_path_factory.mktemp("pg")
    port = _free_port()
    subprocess.run([PG_BIN / "initdb", "-D", data, "-U", "postgres", "-A", "trust"], check=True, capture_output=True)
    subprocess.run([PG_BIN / "pg_ctl", "-D", data, "-o", f"-p {port} -c unix_socket_directories=''", "-l", data / "log", "-w", "start"],
                   check=True, capture_output=True)
    url = f"postgresql://postgres@127.0.0.1:{port}/postgres"
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("create role anon nologin; create role authenticated nologin;")
    yield url
    subprocess.run([PG_BIN / "pg_ctl", "-D", data, "-m", "immediate", "stop"], capture_output=True)
    shutil.rmtree(data, ignore_errors=True)


@pytest.fixture
def admin(pg_url):
    """Superuser connection, used only for setup through the loader's own functions."""
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute("drop schema if exists public cascade; create schema public;")
        apply_migration(conn)
        yield conn


@pytest.fixture
def connect(pg_url, admin):
    """Open connections that act as the public site does: role anon, RPC functions only."""
    opened = []

    def _connect():
        conn = psycopg.connect(pg_url, autocommit=True)
        conn.execute("set role anon")
        opened.append(conn)
        return conn

    yield _connect
    for c in opened:
        c.close()
