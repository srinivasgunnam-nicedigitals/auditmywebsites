import sqlite3
import os

db_path = "sitetoolpro.db"

if not os.path.exists(db_path):
    print(f"Database {db_path} not found.")
    exit(1)

con = sqlite3.connect(db_path)
cur = con.cursor()
try:
    cur.execute("ALTER TABLE meta_tags_results ADD COLUMN images_alt TEXT")
    print("Column images_alt added successfully.")
except sqlite3.OperationalError as e:
    print(f"Operation failed (column likely exists): {e}")

con.commit()
con.close()
