"""ngrok tunnel keeper - saves URL to file"""
import os, time, subprocess, sys

# Clear proxy
for k in list(os.environ.keys()):
    if 'proxy' in k.lower() or 'PROXY' in k:
        del os.environ[k]

from pyngrok import ngrok, conf
conf.get_default().auth_token = "3H85vieeJIODOR5lrowfObF3aKo_7y3So59yAJdXQxn82K29K"

tunnel = ngrok.connect(5001, "http")
url = tunnel.public_url

# Save to file
url_file = r"C:\Users\po\WorkBuddy\2026-07-21-15-26-10\song-web\tunnel_url.txt"
with open(url_file, "w") as f:
    f.write(url)

print(f"TUNNEL_OK:{url}", flush=True)

# Keep alive
while True:
    time.sleep(3600)
