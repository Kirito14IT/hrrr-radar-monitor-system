# db.py（更新版）
import pymysql
import bcrypt

DB_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '123456',
    'database': 'user_data',
    'charset': 'utf8mb4'
}

def hash_password(password: str) -> str:
    """对密码进行 bcrypt 哈希"""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verify_password(password: str, hashed: str) -> bool:
    """验证密码是否匹配哈希值"""
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

class Database:
    def __init__(self):
        self.connection = None
        self.connect()

    def connect(self):
        """建立数据库连接"""
        try:
            self.connection = pymysql.connect(**DB_CONFIG)
            print("✅ 数据库连接成功")
        except Exception as e:
            print(f"❌ 数据库连接失败: {e}")
            raise

    def close(self):
        """关闭数据库连接"""
        if self.connection and self.connection.open:
            self.connection.close()
            print("🔌 数据库连接已关闭")

    def execute(self, sql, params=None):
        """执行 SQL 语句"""
        cursor = None
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, params or ())
            self.connection.commit()
            return cursor
        except Exception as e:
            self.connection.rollback()
            print(f"❌ 执行 SQL 失败: {sql}, 错误: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def fetch_all(self, sql, params=None):
        """查询所有结果"""
        cursor = None
        try:
            cursor = self.connection.cursor(pymysql.cursors.DictCursor)
            cursor.execute(sql, params or ())
            return cursor.fetchall()
        except Exception as e:
            print(f"❌ 查询失败: {sql}, 错误: {e}")
            raise
        finally:
            if cursor:
                cursor.close()

    def fetch_one(self, sql, params=None):
        """查询单条记录"""
        cursor = None
        try:
            cursor = self.connection.cursor(pymysql.cursors.DictCursor)
            cursor.execute(sql, params or ())
            return cursor.fetchone()
        except Exception as e:
            print(f"❌ 查询失败: {sql}, 错误: {e}")
            raise
        finally:
            if cursor:
                cursor.close()


# ==================== user_info 表操作 ====================
def create_user(user_name, password, email):
    """插入用户信息（自动分配 userID）"""
    db = Database()
    try:
        # 检查用户名或邮箱是否已存在
        existing = db.fetch_one("SELECT userID FROM user_info WHERE userName = %s OR email = %s", (user_name, email))
        if existing:
            raise ValueError("用户名或邮箱已存在")

        hashed_pw = hash_password(password)
        sql = "INSERT INTO user_info (userName, passWord, email) VALUES (%s, %s, %s)"
        cursor = db.execute(sql, (user_name, hashed_pw, email))
        user_id = cursor.lastrowid  # 获取自增ID
        print(f"✅ 用户 {user_name} (ID={user_id}) 创建成功")
        return user_id
    except Exception as e:
        print(f"❌ 创建用户失败: {e}")
        raise
    finally:
        db.close()

def get_user_by_username(username):
    """根据 userName 查询用户（用于登录）"""
    db = Database()
    try:
        sql = "SELECT * FROM user_info WHERE userName = %s"
        result = db.fetch_one(sql, (username,))
        return result
    except Exception as e:
        print(f"❌ 查询用户失败: {e}")
        return None
    finally:
        db.close()

def update_user(user_id, user_name=None, password=None, email=None):
    """更新用户信息"""
    db = Database()
    try:
        sql = "UPDATE user_info SET "
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

        set_parts.append("userID = %s")
        params.append(user_id)

        sql += ", ".join(set_parts)
        sql += " WHERE userID = %s"
        params.append(user_id)

        db.execute(sql, tuple(params))
        print(f"✅ 用户 {user_id} 更新成功")
    except Exception as e:
        print(f"❌ 更新用户失败: {e}")
    finally:
        db.close()

def delete_user(user_id):
    """删除用户"""
    db = Database()
    try:
        sql = "DELETE FROM user_info WHERE userID = %s"
        db.execute(sql, (user_id,))
        print(f"✅ 用户 {user_id} 删除成功")
    except Exception as e:
        print(f"❌ 删除用户失败: {e}")
    finally:
        db.close()

def list_all_users():
    """查询所有用户"""
    db = Database()
    try:
        sql = "SELECT * FROM user_info"
        users = db.fetch_all(sql)
        return users
    except Exception as e:
        print(f"❌ 查询用户列表失败: {e}")
    finally:
        db.close()


# ==================== heart_data 表操作 ====================
def save_vitals_with_user(user_id, heart_rate, breath_rate, target_distance, timestamp_str=None):
    """保存带用户ID的生命体征数据"""
    db = Database()
    try:
        # 如果提供了 ISO 时间字符串，则转换为 MySQL DATETIME 格式
        if timestamp_str:
            from datetime import datetime
            dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            mysql_timestamp = dt.strftime('%Y-%m-%d %H:%M:%S')
        else:
            mysql_timestamp = None  # 使用数据库默认当前时间

        sql = """
        INSERT INTO heart_data (userID, heart_rate, breath_rate, target_distance, timestamp)
        VALUES (%s, %s, %s, %s, %s)
        """
        params = (user_id, heart_rate, breath_rate, target_distance, mysql_timestamp)
        cursor = db.execute(sql, params)
        data_id = cursor.lastrowid
        print(f"✅ 生命体征数据已保存，dataID={data_id}, userID={user_id}")
        return data_id
    except Exception as e:
        print(f"❌ 保存生命体征失败: {e}")
        raise
    finally:
        db.close()

# ==================== heart_data 查询 ====================
def query_heart_data_by_date(page_num: int, page_size: int, date_str: str = None, user_id: int = None):
    """
    按日期和用户ID分页查询心率数据
    :param page_num: 页码
    :param page_size: 每页数量
    :param date_str: 日期字符串，格式 'YYYY/MM/DD' 或 None
    :param user_id: 用户ID，用于过滤数据（可选）
    :return: {'list': [...], 'total': int}
    """
    db = Database()
    try:
        offset = (page_num - 1) * page_size

        where_clause = []
        params = []

        if user_id:
            where_clause.append("userID = %s")
            params.append(user_id)

        if date_str:
            where_clause.append("DATE(timestamp) = %s")
            params.append(date_str)

        # 构造主查询 SQL
        sql = """
            SELECT dataID, userID, 
                   YEAR(timestamp) AS year,
                   MONTH(timestamp) AS month,
                   DAY(timestamp) AS day,
                   heart_rate AS bpm_rader,
                   breath_rate AS bpm_finger
            FROM heart_data
        """
        if where_clause:
            sql += " WHERE " + " AND ".join(where_clause)
        sql += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
        params.extend([page_size, offset])

        data_list = db.fetch_all(sql, tuple(params))

        # 构造总数查询
        total_sql = "SELECT COUNT(*) AS total FROM heart_data"
        if where_clause:
            total_sql += " WHERE " + " AND ".join(where_clause)
        total_params = tuple(params[:-2])  # 去掉 LIMIT 和 OFFSET 参数

        total_res = db.fetch_one(total_sql, total_params)
        total = total_res['total'] if total_res else 0

        return {
            'list': data_list,
            'total': total
        }
    except Exception as e:
        print(f"❌ 查询心率数据失败: {e}")
        raise
    finally:
        db.close()