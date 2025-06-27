import os
import pickle
import requests
import webbrowser
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from kiteconnect import KiteConnect, exceptions

# Load environment variables
load_dotenv()

# Kite credentials
KITE_API_KEY = os.getenv("KITE_API_KEY")
KITE_API_SECRET = os.getenv("KITE_API_SECRET")
KITE_TOKEN_FILE = "auth/kite_access_token.pkl"

# Upstox credentials
UPSTOX_API_KEY = os.getenv("UPSTOX_API_KEY")
UPSTOX_API_SECRET = os.getenv("UPSTOX_API_SECRET")
UPSTOX_REDIRECT_URI = "http://localhost"
UPSTOX_TOKEN_FILE = "auth/upstox_access_token.pkl"

# Ensure token directories exist
os.makedirs(os.path.dirname(KITE_TOKEN_FILE), exist_ok=True)
os.makedirs(os.path.dirname(UPSTOX_TOKEN_FILE), exist_ok=True)

def save_token(token: str, token_file: str):
    with open(token_file, "wb") as f:
        pickle.dump(token, f)

def load_token(token_file: str) -> str | None:
    if os.path.exists(token_file):
        with open(token_file, "rb") as f:
            return pickle.load(f)
    return None

# Kite token management
def generate_new_kite_token(kite: KiteConnect) -> str:
    login_url = kite.login_url()
    print(f"🔐 Login URL: {login_url}")
    webbrowser.open(login_url)

    full_url = input("📥 Paste the full redirected URL after login: ")
    parsed_url = urlparse(full_url)
    request_token = parse_qs(parsed_url.query).get("request_token", [None])[0]

    if not request_token:
        raise ValueError("❌ Could not extract request_token from the URL.")

    data = kite.generate_session(request_token, api_secret=KITE_API_SECRET)
    access_token = data["access_token"]
    save_token(access_token, KITE_TOKEN_FILE)
    print("✅ New Kite access token generated and saved.")
    return access_token

def get_valid_kite_access_token(kite: KiteConnect) -> str:
    access_token = load_token(KITE_TOKEN_FILE)
    if access_token:
        try:
            kite.set_access_token(access_token)
            kite.profile()
            return access_token
        except exceptions.TokenException:
            print("⚠️ Kite access token expired.")
        except Exception as e:
            print(f"⚠️ Error validating Kite token: {e}")
    print("🔁 Generating a new Kite access token...")
    return generate_new_kite_token(kite)

def get_kite_session() -> KiteConnect:
    kite = KiteConnect(api_key=KITE_API_KEY)
    access_token = get_valid_kite_access_token(kite)
    kite.set_access_token(access_token)
    return kite

# Upstox token management
def generate_new_upstox_token() -> str:
    login_url = (
        f"https://api.upstox.com/v2/login/authorization/dialog?"
        f"response_type=code&client_id={UPSTOX_API_KEY}&redirect_uri={UPSTOX_REDIRECT_URI}"
    )
    print("🔗 Opening Upstox login URL in your browser...")
    webbrowser.open(login_url)

    redirected_url = input("✅ Paste the FULL redirected URL after login:\n")
    code = parse_qs(urlparse(redirected_url).query).get("code", [None])[0]

    token_payload = {
        "code": code,
        "client_id": UPSTOX_API_KEY,
        "client_secret": UPSTOX_API_SECRET,
        "redirect_uri": UPSTOX_REDIRECT_URI,
        "grant_type": "authorization_code"
    }

    response = requests.post("https://api.upstox.com/v2/login/authorization/token", data=token_payload)
    access_token = response.json().get("access_token")

    if access_token:
        save_token(access_token, UPSTOX_TOKEN_FILE)
        print("✅ Upstox access token stored.")
        return access_token
    else:
        print("❌ Failed to retrieve Upstox access token.")
        return None

def get_valid_upstox_access_token() -> str:
    access_token = load_token(UPSTOX_TOKEN_FILE)
    if access_token:
        return access_token
    print("🔁 Generating a new Upstox access token...")
    return generate_new_upstox_token()

