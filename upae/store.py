"""SQLite persistence with FTS5 lexical search.

The schema mirrors what a PostgreSQL deployment would use (one table per object
type, JSON payload column + indexed key columns, full-text index over
proposition text and quotes).  SQLite keeps the MVP dependency-free and locally
testable; see docs/SYSTEM_ARCHITECTURE.md §5 for the migration path.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, key TEXT UNIQUE, kind TEXT, independence_group TEXT,
    retracted INTEGER, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS passages (id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
    page INTEGER, section TEXT, language TEXT, text TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS propositions (id TEXT PRIMARY KEY, fingerprint TEXT UNIQUE, claim_type TEXT,
    source_id TEXT NOT NULL REFERENCES sources(id), passage_id TEXT REFERENCES passages(id),
    text TEXT, quote TEXT, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence (id TEXT PRIMARY KEY, proposition_id TEXT NOT NULL REFERENCES propositions(id),
    stance TEXT, strength REAL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS relations (id TEXT PRIMARY KEY, type TEXT, source TEXT NOT NULL REFERENCES propositions(id),
    target TEXT NOT NULL REFERENCES propositions(id), payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS assessments (proposition_id TEXT PRIMARY KEY REFERENCES propositions(id), status TEXT,
    confidence REAL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS issues (id TEXT PRIMARY KEY, category TEXT, finding_class TEXT, severity TEXT,
    red INTEGER, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_rel_src ON relations(source);
CREATE INDEX IF NOT EXISTS ix_rel_tgt ON relations(target);
CREATE INDEX IF NOT EXISTS ix_ev_prop ON evidence(proposition_id);
CREATE VIRTUAL TABLE IF NOT EXISTS proposition_fts USING fts5(id UNINDEXED, text, quote, tokenize='unicode61');
"""


def save(snapshot: dict, path: str | Path) -> None:
    path = Path(path)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(DDL)
    j = lambda o: json.dumps(o, ensure_ascii=False)  # noqa: E731
    with con:
        con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (snapshot["schema_version"],))
        con.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?)",
                        [(s["id"], s["key"], s["kind"], s["independence_group"], int(s["retracted"]), j(s))
                         for s in snapshot["sources"]])
        con.executemany("INSERT INTO passages VALUES (?,?,?,?,?,?,?)",
                        [(p["id"], p["source_id"], p["page"], p["section"], p["language"], p["text"], j(p))
                         for p in snapshot["passages"]])
        con.executemany("INSERT INTO propositions VALUES (?,?,?,?,?,?,?,?)",
                        [(p["id"], p["fingerprint"], p["claim_type"], p["source_refs"][0], p["passage_id"],
                          p["text"], p["quote"], j(p)) for p in snapshot["propositions"]])
        con.executemany("INSERT INTO proposition_fts VALUES (?,?,?)",
                        [(p["id"], p["text"], p["quote"]) for p in snapshot["propositions"]])
        con.executemany("INSERT INTO evidence VALUES (?,?,?,?,?)",
                        [(e["id"], e["proposition_id"], e["stance"], e["strength"], j(e))
                         for e in snapshot["evidence"]])
        con.executemany("INSERT INTO relations VALUES (?,?,?,?,?)",
                        [(r["id"], r["type"], r["source"], r["target"], j(r)) for r in snapshot["relations"]])
        con.executemany("INSERT INTO assessments VALUES (?,?,?,?)",
                        [(a["proposition_id"], a["status"], a["confidence"], j(a))
                         for a in snapshot["assessments"]])
        con.executemany("INSERT INTO issues VALUES (?,?,?,?,?,?)",
                        [(i["id"], i["category"], i["finding_class"], i["severity"], int(i["red"]), j(i))
                         for i in snapshot["issues"]])
    con.close()


def search(path: str | Path, query: str, limit: int = 20) -> list[dict]:
    """Full-text search over propositions; returns id, text, status, source."""
    con = sqlite3.connect(path)
    terms = " OR ".join(f'"{t}"' for t in query.replace('"', " ").split() if t)
    if not terms:
        return []
    rows = con.execute(
        "SELECT f.id, p.text, a.status, p.source_id, bm25(proposition_fts) AS score "
        "FROM proposition_fts f JOIN propositions p ON p.id = f.id "
        "LEFT JOIN assessments a ON a.proposition_id = p.id "
        "WHERE proposition_fts MATCH ? ORDER BY score LIMIT ?", (terms, limit)).fetchall()
    con.close()
    return [{"id": r[0], "text": r[1], "status": r[2], "source": r[3], "score": round(r[4], 3)} for r in rows]
