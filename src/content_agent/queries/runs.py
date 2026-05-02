from content_agent.db import _fetchall


def start(conn) -> int:
    cur = conn.cursor()
    cur.execute("INSERT INTO runs (started_at) VALUES (NOW()) RETURNING id")
    run_id = cur.fetchone()["id"]
    conn.commit()
    cur.close()
    return run_id


def finish(
    conn,
    run_id: int,
    episodes_discovered: int,
    episodes_processed: int,
    episodes_failed: int,
    articles_discovered: int = 0,
    articles_processed: int = 0,
    articles_failed: int = 0,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """UPDATE runs SET
           finished_at = NOW(),
           episodes_discovered = %s,
           episodes_processed = %s,
           episodes_failed = %s,
           articles_discovered = %s,
           articles_processed = %s,
           articles_failed = %s
           WHERE id = %s""",
        (
            episodes_discovered,
            episodes_processed,
            episodes_failed,
            articles_discovered,
            articles_processed,
            articles_failed,
            run_id,
        ),
    )
    conn.commit()
    cur.close()


def get_all(conn) -> list:
    return _fetchall(conn, "SELECT * FROM runs ORDER BY started_at DESC")


def get_dashboard_stats(conn) -> dict:
    cur = conn.cursor()

    cur.execute("SELECT status, COUNT(*) as count FROM episodes GROUP BY status")
    by_status = {row["status"]: row["count"] for row in cur.fetchall()}

    cur.execute(
        "SELECT COUNT(*) as count FROM episodes WHERE discovered_at::DATE = CURRENT_DATE"
    )
    today_count = cur.fetchone()["count"]

    cur.execute(
        "SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1"
    )
    last_run_row = cur.fetchone()
    cur.close()

    return {
        "by_status": by_status,
        "today_count": today_count,
        "last_run": dict(last_run_row) if last_run_row else None,
        "total": sum(by_status.values()),
    }
