import json

from content_agent.db import _execute, _fetchall
from content_agent.models import TaskModelOverride


def get_task_overrides(conn) -> dict[str, TaskModelOverride]:
    rows = _fetchall(conn, "SELECT key, value FROM settings WHERE key LIKE 'task_model:%%'")
    overrides = {}
    for row in rows:
        task_name = row["key"].removeprefix("task_model:")
        overrides[task_name] = TaskModelOverride(**json.loads(row["value"]))
    return overrides


def set_task_override(conn, task_name: str, override: TaskModelOverride) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES (%s, %s, NOW())
           ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at""",
        (f"task_model:{task_name}", override.model_dump_json()),
    )
    conn.commit()
    cur.close()


def delete_task_override(conn, task_name: str) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM settings WHERE key = %s", (f"task_model:{task_name}",))
    conn.commit()
    cur.close()
