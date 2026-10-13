from google_auth_oauthlib.flow import InstalledAppFlow
CLIENT_ID = "YOUR_ID.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-..."
flow = InstalledAppFlow.from_client_config(
  {"installed": {"client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "redirect_uris": ["http://localhost:8080/"]}},
  scopes=["https://www.googleapis.com/auth/youtube.upload","https://www.googleapis.com/auth/youtube"]
)
flow.redirect_uri = "http://localhost:8080/"
auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
print(f"Open: {auth_url}")
from urllib.parse import urlparse, parse_qs
resp = input("Paste full redirect URL: ")
code = parse_qs(urlparse(resp).query).get('code', [resp])[0]
flow.fetch_token(code=code)
print("REFRESH_TOKEN:", flow.credentials.refresh_token)
