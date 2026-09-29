import json
import time

ACTIVE_PROFILE = "active_profile"


def get_profiles(con):
    return {
        r["id"]: json.loads(r["data"])
        for r in con.execute("SELECT id, data FROM profiles ORDER BY id")
    }


def save_profile(con, profile_id, data, now=None):
    if not isinstance(data, dict):
        raise ValueError("a profile must be a JSON object")
    now = int(now if now is not None else time.time())
    con.execute(
        "INSERT INTO profiles (id, data, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
        (profile_id, json.dumps(data, ensure_ascii=False), now),
    )
    con.commit()
    return data


def delete_profile(con, profile_id):
    cur = con.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
    con.commit()
    return cur.rowcount > 0


def get_settings(con):
    return {
        r["key"]: json.loads(r["value"])
        for r in con.execute("SELECT key, value FROM settings")
    }


def set_setting(con, key, value, now=None):
    now = int(now if now is not None else time.time())
    con.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, json.dumps(value, ensure_ascii=False), now),
    )
    con.commit()
    return value
