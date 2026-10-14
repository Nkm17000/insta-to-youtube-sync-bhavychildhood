"""
AUTO refresh token generator - ONLY CLIENT_ID and CLIENT_SECRET needed
No manual URL paste
"""
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_ID = input("Enter CLIENT_ID: ").strip()
CLIENT_SECRET = input("Enter CLIENT_SECRET: ").strip()

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube"
]

print("\nOpening browser... Login with YOUR YOUTUBE CHANNEL Gmail and click Allow")
print("After Allow, browser shows Success - No URL to copy!")

flow = InstalledAppFlow.from_client_config(
    {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost:8080/"]
        }
    },
    SCOPES
)

creds = flow.run_local_server(
    port=8080,
    prompt='consent',
    access_type='offline',
    open_browser=True,
    success_message='<h1>Success!</h1><p>Close this window. Check terminal for REFRESH_TOKEN.</p>'
)

print("\n" + "="*70)
print("COPY THESE:")
print("="*70)
print(f"CLIENT_ID: {CLIENT_ID}")
print(f"CLIENT_SECRET: {CLIENT_SECRET}")
print(f"REFRESH_TOKEN: {creds.refresh_token}")
print("="*70)
print("\nSave as GitHub Secrets:")
print(f"YT1_CLIENT_ID={CLIENT_ID}")
print(f"YT1_CLIENT_SECRET={CLIENT_SECRET}")
print(f"YT1_REFRESH_TOKEN={creds.refresh_token}")
