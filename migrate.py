"""独立迁移入口：uv run python migrate.py 执行所有未应用的迁移。"""

from db import get_connection, migrate

if __name__ == "__main__":
    conn = get_connection()
    print("=== 检查并执行数据库迁移 ===")
    migrate(conn)
    conn.close()
    print("迁移完成。")
