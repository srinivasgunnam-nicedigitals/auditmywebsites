
import requests
from bs4 import BeautifulSoup
import json

# URL of the running server
BASE_URL = "http://192.168.0.136:8001"

def test_new_user_stats():
    print(f"Connecting to {BASE_URL}...")
    
    username = "debug_new_user_888"
    email = "debug_new_user_888@example.com"
    password = "password123"
    
    session = requests.Session()
    
    # 1. Register
    register_url = f"{BASE_URL}/api/auth/register"
    print(f"Registering new user: {email} at {register_url}")

    try:
        reg_resp = session.post(register_url, json={
            "username": username,
            "email": email,
            "password": password
        })
    except Exception as e:
        print(f"Registration request failed: {e}")
        return

    print(f"Register status: {reg_resp.status_code}")
    
    if reg_resp.status_code != 200:
        print(f"Register failed: {reg_resp.text}")
        # Try login if user exists
        login_url = f"{BASE_URL}/api/auth/login"
        print(f"Trying login at {login_url}")
        login_resp = session.post(login_url, json={ # Login usually takes json or form data depending on implementation
             "username": username,
             "password": password
        })
        # If standard OAuth2 form request
        if login_resp.status_code != 200:
             login_resp = session.post(login_url, data={
                 "username": username,
                 "password": password
             })
        
        if login_resp.status_code == 200:
            data = login_resp.json()
            token = data.get("access_token")
            # Set cookie
            session.cookies.set("access_token", token)
            print("Login successful.")
        else:
            print("Login failed.")
            return
    else:
        # Register success
        data = reg_resp.json()
        token = data.get("access_token")
        if token:
            session.cookies.set("access_token", token)
            print("Registration returned token. Logged in.")
        else:
            print("Registration success but no token. Trying login manually...")
            # Manual login logic here if needed
            return

    # 3. Access Profile Page
    print("Fetching profile page...")
    profile_resp = session.get(f"{BASE_URL}/platform/profile")
    
    if profile_resp.status_code != 200:
        print(f"Failed to get profile: {profile_resp.status_code}")
        return

    # 4. Parse HTML and find Stats
    soup = BeautifulSoup(profile_resp.text, 'html.parser')
    
    total_audits_label = soup.find("div", string="Total Audits Run")
    if total_audits_label:
        parent = total_audits_label.parent
        value_div = parent.find("div", class_="value")
        total_audits = value_div.get_text(strip=True)
        print(f"Total Audits Run: '{total_audits}'")
    else:
        print("Could not find 'Total Audits Run' label")

    success_rate_label = soup.find("div", string="Success Rate")
    if success_rate_label:
        parent = success_rate_label.parent
        value_div = parent.find("div", class_="value")
        success_rate = value_div.get_text(strip=True)
        print(f"Success Rate: '{success_rate}'")
    else:
        print("Could not find 'Success Rate' label")

if __name__ == "__main__":
    test_new_user_stats()
