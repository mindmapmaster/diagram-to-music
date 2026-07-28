"""持久化隧道脚本 - 后台运行，断开不杀"""
import subprocess, sys, time, json

PORT = 5001
TUNNEL_FILE = r"C:\Users\po\WorkBuddy\2026-07-21-15-26-10\song-web\tunnel_url.txt"

proc = subprocess.Popen(
    ['ssh', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
     '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3',
     '-p', '443', '-R', f'0:localhost:{PORT}', 'a.pinggy.io'],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
)

for line in proc.stdout:
    ls = line.strip()
    if ls:
        print(ls, flush=True)
    if 'pinggy' in ls and (ls.startswith('https://') or ls.startswith('http://')):
        with open(TUNNEL_FILE, 'w') as f:
            f.write(ls.strip())
        print(f'\n===== 隧道链接: {ls.strip()} =====', flush=True)
        print(f'已写入: {TUNNEL_FILE}', flush=True)
