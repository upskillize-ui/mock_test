#!/usr/bin/env python3
"""DB POOL + CONNECTION AUDIT — Capacity/Cost phase, item 6.

READ-ONLY. Connects to the same Aiven MySQL the Space uses (DATABASE_URL from backend/.env)
and reports the numbers the capacity plan needs:

  * Aiven's server-side ceiling:  max_connections, max_user_connections
  * live pressure:                Threads_connected, Max_used_connections (high-water mark)
  * who is holding them:          connection count per user (Space vs LMS), per host
  * the Space's own ceiling:      pool_size + max_overflow  (from app.config)

Then it does the arithmetic that matters: does (Space pool ceiling + observed LMS usage) fit
under Aiven's cap, with headroom? Because a request PINS its pooled connection across the
whole multi-second LLM await, the Space pool ceiling is also a hard cap on concurrent
LLM-bearing requests — so this ceiling is both a DB-sharing number and a concurrency number.

Run from a host allowlisted on the Aiven service (the numbers, not the writes, are the point):
    python scripts/db_pool_audit.py
"""
import os
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")  # ₹ and — on a cp1252 console
except Exception:
    pass
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(BACKEND / ".env")

from sqlalchemy import create_engine, text  # noqa: E402


def _var(conn, name):
    r = conn.execute(text(f"SHOW VARIABLES LIKE '{name}'")).first()
    return r[1] if r else None


def _status(conn, name):
    r = conn.execute(text(f"SHOW STATUS LIKE '{name}'")).first()
    return r[1] if r else None


def main() -> int:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        print("FAIL: DATABASE_URL not set in backend/.env")
        return 1

    # The Space's own pool ceiling, straight from the app config (single source of truth).
    try:
        from app.config import settings
        pool_size = settings.DB_POOL_SIZE
        overflow = settings.DB_MAX_OVERFLOW
    except Exception:
        pool_size, overflow = 5, 10
    space_ceiling = pool_size + overflow

    print("=" * 70)
    print("DB POOL + CONNECTION AUDIT (read-only)")
    print("=" * 70)
    print(f"Space pool config : pool_size={pool_size} + max_overflow={overflow} "
          f"-> ceiling {space_ceiling} connections PER WORKER")
    print("  (single uvicorn worker in the Dockerfile/render.yaml -> one pool)")
    print("  NOTE: a request holds its pooled connection across the LLM await, so this")
    print("        ceiling is also the cap on concurrent LLM-bearing requests.\n")

    try:
        eng = create_engine(url, connect_args={"connect_timeout": 10})
        with eng.connect() as c:
            max_conn = _var(c, "max_connections")
            max_user = _var(c, "max_user_connections")
            threads = _status(c, "Threads_connected")
            high = _status(c, "Max_used_connections")
            print(f"Aiven max_connections        : {max_conn}")
            print(f"Aiven max_user_connections   : {max_user}  (0 = unlimited per user)")
            print(f"Threads_connected (now)      : {threads}")
            print(f"Max_used_connections (peak)  : {high}\n")

            try:
                rows = c.execute(text(
                    "SELECT USER, COUNT(*) AS n FROM information_schema.PROCESSLIST "
                    "GROUP BY USER ORDER BY n DESC"
                )).fetchall()
                print("Connections by user (Space vs LMS live right now):")
                for u, n in rows:
                    print(f"    {u:<24} {n}")
                print()
            except Exception as e:
                print(f"(processlist by user unavailable: {type(e).__name__})\n")

            # The arithmetic.
            print("-" * 70)
            print("ASSESSMENT")
            print("-" * 70)
            try:
                cap = int(max_conn)
                live = int(threads or 0)
                headroom = cap - live
                print(f"  Aiven cap {cap}, {live} in use now -> {headroom} free this instant.")
                print(f"  If the Space fills its pool ({space_ceiling}) while the LMS holds its")
                print(f"  current {max(live - 0, 0)}-ish, the two together approach {space_ceiling + live}.")
                if space_ceiling + live > cap:
                    print("  >>> RISK: Space ceiling + current LMS usage EXCEEDS the Aiven cap.")
                    print("      Under load the Space can starve the LMS (or itself) of connections.")
                    print("      Lower DB_POOL_SIZE/DB_MAX_OVERFLOW, or raise the Aiven plan, or")
                    print("      cap concurrency (MAX_CONCURRENT_SESSIONS) below the pool ceiling.")
                else:
                    print("  >>> OK at current LMS usage — but confirm the LMS's OWN peak, not just now.")
            except (TypeError, ValueError):
                print("  Could not read a numeric max_connections — record it from the Aiven console.")
    except Exception as e:
        print(f"DB unreachable: {type(e).__name__}: {str(e)[:200]}")
        print("\nIf this is 'Access denied' or a timeout, run from a host allowlisted on the")
        print("Aiven service with current credentials — the numbers above are what the report needs.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
