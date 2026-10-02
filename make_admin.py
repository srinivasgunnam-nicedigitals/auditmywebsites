import sqlite3
import sys
import os

db_path = os.path.join("database", "sitetoolpro.db")

def make_admin(email):
    print(f"Connecting to database at {db_path}...")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute("SELECT id, username, is_admin FROM users WHERE email = ?", (email,))
        user_row = cursor.fetchone()
        
        if not user_row:
            print(f"Error: User with email '{email}' not found.")
            conn.close()
            return
            
        user_id, username, is_admin = user_row
        
        if is_admin:
            print(f"User '{username}' ({email}) is already an admin.")
        else:
            print(f"Making user '{username}' ({email}) an admin...")
            cursor.execute("UPDATE users SET is_admin = 1 WHERE email = ?", (email,))
            conn.commit()
            print(f"Successfully updated user '{username}'. They are now an admin!")
            
        conn.close()
    except Exception as e:
        print(f"Database error: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python make_admin.py <user_email>")
        print("Example: python make_admin.py admin@example.com")
    else:
        email = sys.argv[1]
        make_admin(email)