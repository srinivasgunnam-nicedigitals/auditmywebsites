import sys
import os

# Add current directory to path so we can import main
sys.path.append(os.getcwd())

try:
    from main import app
    print("Successfully imported app from main")
    
    print("Listing all dashboard routes:")
    for route in app.routes:
        if hasattr(route, "path") and ("dashboard" in route.path or "platform" in route.path):
            print(f"ROUTE: {route.path} [{','.join(route.methods)}] -> {route.endpoint.__name__}")


except Exception as e:
    print(f"Error importing app: {e}")
