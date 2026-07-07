import os
import json
import sqlite3
from datetime import datetime

import bcrypt


SQLITE_PATH = os.getenv(
    "RADAR_SQLITE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_data.db"),
)
BED_DEVICE_CONFIG_PATH = os.getenv(
    "BED_DEVICE_CONFIG_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "bed_devices.json"),
)

DEFAULT_BED_ID = "bed-001"
DEFAULT_BED_LABEL = "01床"
SIM_BED_ID = "bed-sim-001"
SIM_BED_LABEL = "03床"


def normalize_date_str(date_str: str = None):
    """将前端传入的日期统一成 SQLite DATE() 可比较的 YYYY-MM-DD。"""
    if not date_str:
        return None

    raw = str(date_str).strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return raw.replace("/", "-")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


class Database:
    """SQLite-only database helper.

    本项目现在固定使用 SQLite，避免 MySQL 的 YEAR()/MONTH()/DAY() 等函数
    混入历史记录查询，导致 SQLite 报 `no such function: YEAR`。
    """

    def __init__(self):
        self.connection = None
        self.backend = "sqlite"
        self.connect()

    def connect(self):
        os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
        self.connection = sqlite3.connect(SQLITE_PATH, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS user_info (
                userID INTEGER PRIMARY KEY AUTOINCREMENT,
                userName TEXT NOT NULL UNIQUE,
                passWord TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS heart_data (
                dataID INTEGER PRIMARY KEY AUTOINCREMENT,
                userID INTEGER NOT NULL,
                bed_id TEXT DEFAULT 'bed-001',
                heart_rate REAL,
                breath_rate REAL,
                target_distance REAL,
                snore_detected INTEGER DEFAULT 0,
                snore_score REAL,
                snore_level REAL,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS bed_registry (
                bed_id TEXT PRIMARY KEY,
                bed_label TEXT NOT NULL,
                room TEXT,
                patient_name TEXT NOT NULL,
                patient_gender TEXT,
                patient_age INTEGER,
                patient_note TEXT,
                radar_ip TEXT,
                radar_port INTEGER DEFAULT 9988,
                edgi_device_id TEXT,
                edgi_source TEXT,
                active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );
            """
        )
        self._ensure_heart_data_columns()
        self._ensure_bed_registry()
        self.connection.commit()
        # print(f"[OK] SQLite 数据库已就绪: {SQLITE_PATH}")

    def _ensure_heart_data_columns(self):
        """为旧版 SQLite 数据库补齐历史呼噜字段。"""
        columns = {
            row["name"]
            for row in self.connection.execute("PRAGMA table_info(heart_data)").fetchall()
        }
        migrations = [
            ("bed_id", "ALTER TABLE heart_data ADD COLUMN bed_id TEXT DEFAULT 'bed-001'"),
            ("snore_detected", "ALTER TABLE heart_data ADD COLUMN snore_detected INTEGER DEFAULT 0"),
            ("snore_score", "ALTER TABLE heart_data ADD COLUMN snore_score REAL"),
            ("snore_level", "ALTER TABLE heart_data ADD COLUMN snore_level REAL"),
        ]
        for column, sql in migrations:
            if column not in columns:
                self.connection.execute(sql)
        self.connection.execute(
            "UPDATE heart_data SET bed_id = ? WHERE bed_id IS NULL OR bed_id = ''",
            (DEFAULT_BED_ID,),
        )

    def _ensure_bed_registry(self):
        """保证至少有一个默认床位，旧单设备链路自动落到 bed-001。"""
        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._ensure_bed_row(
            bed_id=DEFAULT_BED_ID,
            bed_label=DEFAULT_BED_LABEL,
            room="护士站默认病房",
            patient_name="默认患者",
            patient_gender=None,
            patient_age=None,
            patient_note="旧单设备数据默认归属床位",
            radar_ip=os.getenv("DEFAULT_RADAR_IP") or None,
            radar_port=int(os.getenv("DEFAULT_RADAR_PORT", "9988")),
            edgi_device_id=os.getenv("DEFAULT_EDGI_DEVICE_ID") or None,
            edgi_source=os.getenv("DEFAULT_EDGI_SOURCE") or "xiaozhi_board",
            sort_order=0,
            now_text=now_text,
        )
        self._ensure_bed_row(
            bed_id=SIM_BED_ID,
            bed_label=SIM_BED_LABEL,
            room="模拟病房",
            patient_name="演示患者",
            patient_gender="女",
            patient_age=72,
            patient_note="用于护士站多床位演示的模拟床位",
            radar_ip="simulated-radar",
            radar_port=9988,
            edgi_device_id="sim-edgi-001",
            edgi_source="sim_xiaozhi_board",
            sort_order=999,
            now_text=now_text,
        )
        for bed in self._load_bed_device_config():
            self._ensure_bed_row(
                bed_id=bed.get("bed_id") or DEFAULT_BED_ID,
                bed_label=bed.get("bed_label") or bed.get("bed_id") or DEFAULT_BED_LABEL,
                room=bed.get("room"),
                patient_name=bed.get("patient_name") or "未登记患者",
                patient_gender=bed.get("patient_gender"),
                patient_age=bed.get("patient_age"),
                patient_note=bed.get("patient_note"),
                radar_ip=bed.get("radar_ip"),
                radar_port=int(bed.get("radar_port") or 9988),
                edgi_device_id=bed.get("edgi_device_id"),
                edgi_source=bed.get("edgi_source"),
                sort_order=int(bed.get("sort_order") or 0),
                now_text=now_text,
            )

    def _load_bed_device_config(self):
        if not BED_DEVICE_CONFIG_PATH or not os.path.exists(BED_DEVICE_CONFIG_PATH):
            return []
        try:
            with open(BED_DEVICE_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[WARN] 床位设备配置读取失败: {BED_DEVICE_CONFIG_PATH}: {exc}")
            return []

        beds = data.get("beds", data) if isinstance(data, dict) else data
        if not isinstance(beds, list):
            print(f"[WARN] 床位设备配置格式无效，应为列表或包含 beds 列表: {BED_DEVICE_CONFIG_PATH}")
            return []

        valid_beds = []
        for item in beds:
            if isinstance(item, dict) and item.get("bed_id"):
                valid_beds.append(item)
        return valid_beds

    def _ensure_bed_row(
        self,
        bed_id,
        bed_label,
        room,
        patient_name,
        patient_gender,
        patient_age,
        patient_note,
        radar_ip,
        radar_port,
        edgi_device_id,
        edgi_source,
        sort_order,
        now_text,
    ):
        existing = self.connection.execute(
            "SELECT bed_id FROM bed_registry WHERE bed_id = ?",
            (bed_id,),
        ).fetchone()
        if existing:
            self.connection.execute(
                """
                UPDATE bed_registry
                SET bed_label = COALESCE(NULLIF(?, ''), bed_label),
                    room = COALESCE(?, room),
                    patient_name = COALESCE(NULLIF(?, ''), patient_name),
                    patient_gender = COALESCE(?, patient_gender),
                    patient_age = COALESCE(?, patient_age),
                    patient_note = COALESCE(?, patient_note),
                    radar_ip = COALESCE(?, radar_ip),
                    radar_port = COALESCE(?, radar_port),
                    edgi_device_id = COALESCE(?, edgi_device_id),
                    edgi_source = COALESCE(?, edgi_source),
                    active = 1,
                    sort_order = COALESCE(?, sort_order),
                    updated_at = ?
                WHERE bed_id = ?
                """,
                (
                    bed_label,
                    room,
                    patient_name,
                    patient_gender,
                    patient_age,
                    patient_note,
                    radar_ip,
                    radar_port,
                    edgi_device_id,
                    edgi_source,
                    sort_order,
                    now_text,
                    bed_id,
                ),
            )
            return
        self.connection.execute(
            """
            INSERT INTO bed_registry
                (bed_id, bed_label, room, patient_name, patient_gender, patient_age,
                 patient_note, radar_ip, radar_port, edgi_device_id, edgi_source,
                 active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                bed_id,
                bed_label,
                room,
                patient_name,
                patient_gender,
                patient_age,
                patient_note,
                radar_ip,
                radar_port,
                edgi_device_id,
                edgi_source,
                sort_order,
                now_text,
                now_text,
            ),
        )

    @staticmethod
    def _prepare_sql(sql):
        return sql.replace("%s", "?")

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None

    def execute(self, sql, params=None):
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute(self._prepare_sql(sql), params or ())
            self.connection.commit()
            return cursor
        except Exception:
            self.connection.rollback()
            raise

    def fetch_all(self, sql, params=None):
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute(self._prepare_sql(sql), params or ())
            return [dict(row) for row in cursor.fetchall()]
        finally:
            if cursor:
                cursor.close()

    def fetch_one(self, sql, params=None):
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute(self._prepare_sql(sql), params or ())
            row = cursor.fetchone()
            return dict(row) if row is not None else None
        finally:
            if cursor:
                cursor.close()


def create_user(user_name, password, email):
    db = Database()
    try:
        existing = db.fetch_one(
            "SELECT userID FROM user_info WHERE userName = %s OR email = %s",
            (user_name, email),
        )
        if existing:
            raise ValueError("用户名或邮箱已存在")

        hashed_pw = hash_password(password)
        cursor = db.execute(
            "INSERT INTO user_info (userName, passWord, email) VALUES (%s, %s, %s)",
            (user_name, hashed_pw, email),
        )
        return cursor.lastrowid
    finally:
        db.close()


def get_user_by_username(username):
    db = Database()
    try:
        return db.fetch_one("SELECT * FROM user_info WHERE userName = %s", (username,))
    finally:
        db.close()


def update_user(user_id, user_name=None, password=None, email=None):
    db = Database()
    try:
        params = []
        set_parts = []

        if user_name:
            set_parts.append("userName = %s")
            params.append(user_name)
        if password:
            set_parts.append("passWord = %s")
            params.append(password)
        if email:
            set_parts.append("email = %s")
            params.append(email)

        if not set_parts:
            return

        params.append(user_id)
        db.execute(
            f"UPDATE user_info SET {', '.join(set_parts)} WHERE userID = %s",
            tuple(params),
        )
    finally:
        db.close()


def delete_user(user_id):
    db = Database()
    try:
        db.execute("DELETE FROM user_info WHERE userID = %s", (user_id,))
    finally:
        db.close()


def list_all_users():
    db = Database()
    try:
        return db.fetch_all("SELECT * FROM user_info")
    finally:
        db.close()


def save_vitals_with_user(
    user_id,
    heart_rate,
    breath_rate,
    target_distance,
    timestamp_str=None,
    snore_detected=False,
    snore_score=None,
    snore_level=None,
    bed_id=DEFAULT_BED_ID,
):
    """保存生命体征数据。timestamp 使用 SQLite 可排序的本地时间文本。"""
    db = Database()
    try:
        if timestamp_str:
            dt = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
            timestamp_text = dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            timestamp_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor = db.execute(
            """
            INSERT INTO heart_data
                (userID, bed_id, heart_rate, breath_rate, target_distance, snore_detected, snore_score, snore_level, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                bed_id or DEFAULT_BED_ID,
                heart_rate,
                breath_rate,
                target_distance,
                1 if snore_detected else 0,
                snore_score,
                snore_level,
                timestamp_text,
            ),
        )
        return cursor.lastrowid
    finally:
        db.close()


def query_heart_data_by_date(
    page_num: int,
    page_size: int,
    date_str: str = None,
    user_id: int = None,
    bed_id: str = None,
):
    """按日期和用户分页查询历史生命体征，只使用 SQLite 函数。"""
    db = Database()
    try:
        page_num = max(1, int(page_num or 1))
        page_size = max(1, int(page_size or 10))
        offset = (page_num - 1) * page_size
        normalized_date = normalize_date_str(date_str)

        where_clause = []
        params = []

        if user_id:
            where_clause.append("userID = %s")
            params.append(user_id)

        if bed_id:
            where_clause.append("COALESCE(bed_id, %s) = %s")
            params.extend([DEFAULT_BED_ID, bed_id])

        if normalized_date:
            where_clause.append("DATE(timestamp) = %s")
            params.append(normalized_date)

        where_sql = f" WHERE {' AND '.join(where_clause)}" if where_clause else ""

        data_sql = f"""
            SELECT
                dataID,
                userID,
                COALESCE(bed_id, 'bed-001') AS bed_id,
                CAST(strftime('%Y', timestamp) AS INTEGER) AS year,
                CAST(strftime('%m', timestamp) AS INTEGER) AS month,
                CAST(strftime('%d', timestamp) AS INTEGER) AS day,
                heart_rate AS bpm_rader,
                breath_rate AS bpm_finger,
                COALESCE(snore_detected, 0) AS snore_detected,
                snore_score,
                snore_level
            FROM heart_data
            {where_sql}
            ORDER BY timestamp DESC
            LIMIT %s OFFSET %s
        """
        data_list = db.fetch_all(data_sql, tuple(params + [page_size, offset]))

        total_sql = f"SELECT COUNT(*) AS total FROM heart_data{where_sql}"
        total_res = db.fetch_one(total_sql, tuple(params))

        return {
            "list": data_list,
            "total": int(total_res["total"]) if total_res else 0,
        }
    finally:
        db.close()


def list_bed_registry(active_only=True):
    db = Database()
    try:
        where_sql = "WHERE active = 1" if active_only else ""
        rows = db.fetch_all(
            f"""
            SELECT
                bed_id,
                bed_label,
                room,
                patient_name,
                patient_gender,
                patient_age,
                patient_note,
                radar_ip,
                radar_port,
                edgi_device_id,
                edgi_source,
                active,
                sort_order,
                created_at,
                updated_at
            FROM bed_registry
            {where_sql}
            ORDER BY sort_order ASC, bed_label ASC, bed_id ASC
            """
        )
        return rows
    finally:
        db.close()


def get_bed_by_id(bed_id):
    db = Database()
    try:
        return db.fetch_one(
            """
            SELECT *
            FROM bed_registry
            WHERE bed_id = %s
            """,
            (bed_id or DEFAULT_BED_ID,),
        )
    finally:
        db.close()


def resolve_bed_id(
    bed_id=None,
    radar_ip=None,
    device_id=None,
    source=None,
    default_bed_id=DEFAULT_BED_ID,
):
    db = Database()
    try:
        if bed_id:
            row = db.fetch_one(
                "SELECT bed_id FROM bed_registry WHERE bed_id = %s AND active = 1",
                (bed_id,),
            )
            if row:
                return row["bed_id"]

        if radar_ip:
            row = db.fetch_one(
                """
                SELECT bed_id FROM bed_registry
                WHERE active = 1 AND radar_ip = %s
                ORDER BY sort_order ASC, bed_label ASC
                LIMIT 1
                """,
                (radar_ip,),
            )
            if row:
                return row["bed_id"]

        if device_id:
            row = db.fetch_one(
                """
                SELECT bed_id FROM bed_registry
                WHERE active = 1 AND edgi_device_id = %s
                ORDER BY sort_order ASC, bed_label ASC
                LIMIT 1
                """,
                (device_id,),
            )
            if row:
                return row["bed_id"]

        if source:
            row = db.fetch_one(
                """
                SELECT bed_id FROM bed_registry
                WHERE active = 1 AND edgi_source = %s
                ORDER BY sort_order ASC, bed_label ASC
                LIMIT 1
                """,
                (source,),
            )
            if row:
                return row["bed_id"]

        row = db.fetch_one(
            "SELECT bed_id FROM bed_registry WHERE bed_id = %s",
            (default_bed_id,),
        )
        return row["bed_id"] if row else DEFAULT_BED_ID
    finally:
        db.close()
