
from google_auth_oauthlib.flow import InstalledAppFlow

CLIENT_ID = input("CLIENT_ID: ").strip()
CLIENT_SECRET = input("CLIENT_SECRET: ").strip()

SCOPES = ["https://www.googleapis.com/auth/youtube.upload","https://www.googleapis.com/auth/youtube"]

flow = InstalledAppFlow.from_client_config(
    {"installed":{"client_id":CLIENT_ID,"client_secret":CLIENT_SECRET,"auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token","redirect_uris":["http://localhost:8080/"]}},
    SCOPES
)

# This automatically starts server and captures
creds = flow.run_local_server(port=8082, prompt='consent', access_type='offline')

print(f"\nREFRESH_TOKEN={creds.refresh_token}")
