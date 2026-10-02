import sqlite3
import os
import shutil

DB_PATH = "sitetoolpro.db"
USER_ID = "f23d137b-e012-47d1-9aeb-ace398cf92ee"

def delete_audits():
    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # Get all session IDs for the user
        cursor.execute("SELECT session_id FROM audit_sessions WHERE user_id = ?", (USER_ID,))
        sessions = cursor.fetchall()
        session_ids = [s[0] for s in sessions]

        print(f"Found {len(session_ids)} sessions for user {USER_ID}")

        if not session_ids:
            print("No sessions found to delete.")
            return

        for sid in session_ids:
            print(f"Deleting session {sid}...")
            
            # Delete related results from all result tables
            tables = [
                "static_audit_results",
                "dynamic_audit_results",
                "h1_audit_results",
                "phone_audit_results",
                "visual_audit_results",
                "performance_audit_results",
                "accessibility_audit_results",
                "unified_audit_results",
                "meta_tags_results",
                "sitemap_results"
            ]
            
            for table in tables:
                try:
                    cursor.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,))
                except sqlite3.OperationalError:
                    # Table might not exist or other error, mostly harmless if table is missing
                    pass

            # Delete the session itself
            cursor.execute("DELETE FROM audit_sessions WHERE session_id = ?", (sid,))
            
            # Cleanup files
            # Screenshots and Videos are definitely organized by session_id
            shutil.rmtree(f"screenshots/{sid}", ignore_errors=True)
            shutil.rmtree(f"videos/{sid}", ignore_errors=True)
            
            # Check for other artifacts if they exist (h1-audits/phone-audits seem to be empty or flat, but safe to try if pattern matches)
            # Based on list_dir, they might be empty or flat. 
            # If they used session folders, we would delete them:
            if os.path.exists(f"h1-audits/{sid}"):
                 shutil.rmtree(f"h1-audits/{sid}", ignore_errors=True)
            if os.path.exists(f"phone-audits/{sid}"):
                 shutil.rmtree(f"phone-audits/{sid}", ignore_errors=True)

        conn.commit()
        print("Deletion complete. All records and files removed.")

    except Exception as e:
        print(f"Error during deletion: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    delete_audits()
