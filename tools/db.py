"""
F95Checker database testing utility.

Usage (run from repo root with .venv active):
    python tools/db.py                   # interactive summary
    python tools/db.py clear-games       # delete all games + timeline events
    python tools/db.py backup            # copy db to db.sqlite3.bak
    python tools/db.py restore           # restore from db.sqlite3.bak
    python tools/db.py list              # list all games (id, name, version, installed)
    python tools/db.py find <name>       # find games matching name (case-insensitive)
    python tools/db.py set-installed <id> <version>  # set installed version on a game
    python tools/db.py clear-installed   # clear installed version on ALL games
    python tools/db.py sql <query>       # run arbitrary SQL and print results

WARNING: close F95Checker before running — it holds the DB open and auto-saves every 30s.
"""
import os
import pathlib
import shutil
import sqlite3
import sys


def db_path() -> pathlib.Path:
    if sys.platform.startswith("win"):
        return pathlib.Path(os.environ["APPDATA"]) / "f95checker" / "db.sqlite3"
    elif sys.platform.startswith("linux"):
        return pathlib.Path.home() / ".config" / "f95checker" / "db.sqlite3"
    elif sys.platform.startswith("darwin"):
        return pathlib.Path.home() / "Library" / "Application Support" / "f95checker" / "db.sqlite3"
    else:
        raise RuntimeError("Unsupported platform")


def connect():
    path = db_path()
    if not path.exists():
        print(f"DB not found at: {path}")
        sys.exit(1)
    return sqlite3.connect(path), path


def summary(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM games")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM games WHERE installed != ''")
    installed = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM games WHERE updated = 1")
    outdated = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM timeline_events")
    events = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM labels")
    labels = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tabs")
    tabs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM cookies")
    cookies = cur.fetchone()[0]
    print(f"DB: {db_path()}")
    print(f"  games:           {total}")
    print(f"  installed:       {installed}")
    print(f"  outdated:        {outdated}")
    print(f"  timeline events: {events}")
    print(f"  labels:          {labels}")
    print(f"  tabs:            {tabs}")
    print(f"  cookies:         {cookies}")


def list_games(conn, where="", params=()):
    cur = conn.cursor()
    query = f"SELECT id, name, version, installed, updated FROM games {where} ORDER BY name"
    cur.execute(query, params)
    rows = cur.fetchall()
    if not rows:
        print("(no games)")
        return
    print(f"{'ID':>10}  {'Name':<50}  {'Version':<20}  {'Installed':<20}  Updated")
    print("-" * 115)
    for row in rows:
        id_, name, version, installed, updated = row
        print(f"{id_:>10}  {(name or ''):<50}  {(version or ''):<20}  {(installed or ''):<20}  {updated}")


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "summary"

    conn, path = connect()

    try:
        if cmd == "summary":
            summary(conn)

        elif cmd == "list":
            list_games(conn)

        elif cmd == "find":
            if len(args) < 2:
                print("Usage: db.py find <name>")
                sys.exit(1)
            term = f"%{args[1]}%"
            list_games(conn, "WHERE name LIKE ?", (term,))

        elif cmd == "clear-games":
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM games")
            n = cur.fetchone()[0]
            confirm = input(f"Delete {n} games and all timeline events? [y/N] ").strip().lower()
            if confirm == "y":
                conn.execute("DELETE FROM timeline_events")
                conn.execute("DELETE FROM games")
                conn.commit()
                print(f"Deleted {n} games and all timeline events.")
            else:
                print("Aborted.")

        elif cmd == "backup":
            bak = path.with_suffix(".sqlite3.bak")
            shutil.copy2(path, bak)
            print(f"Backed up to: {bak}")

        elif cmd == "restore":
            bak = path.with_suffix(".sqlite3.bak")
            if not bak.exists():
                print(f"No backup found at: {bak}")
                sys.exit(1)
            shutil.copy2(bak, path)
            print(f"Restored from: {bak}")

        elif cmd == "set-installed":
            if len(args) < 3:
                print("Usage: db.py set-installed <id> <version>")
                sys.exit(1)
            game_id = int(args[1])
            version = args[2]
            conn.execute(
                "UPDATE games SET installed = ?, updated = 1 WHERE id = ?",
                (version, game_id)
            )
            conn.commit()
            print(f"Set game {game_id} installed = '{version}'")

        elif cmd == "clear-installed":
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM games WHERE installed != ''")
            n = cur.fetchone()[0]
            confirm = input(f"Clear installed version on {n} games? [y/N] ").strip().lower()
            if confirm == "y":
                conn.execute("UPDATE games SET installed = '', updated = NULL")
                conn.commit()
                print(f"Cleared {n} games.")
            else:
                print("Aborted.")

        elif cmd == "sql":
            if len(args) < 2:
                print("Usage: db.py sql <query>")
                sys.exit(1)
            query = " ".join(args[1:])
            cur = conn.cursor()
            cur.execute(query)
            if cur.description:
                headers = [d[0] for d in cur.description]
                print("  ".join(f"{h:<20}" for h in headers))
                print("-" * (22 * len(headers)))
                for row in cur.fetchall():
                    print("  ".join(f"{str(v):<20}" for v in row))
            else:
                conn.commit()
                print(f"OK ({cur.rowcount} rows affected)")

        else:
            print(__doc__)
            sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
