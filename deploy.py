"""Deploy song-web to Aliyun ECS"""
import paramiko
import time

HOST = "8.218.175.62"
USER = "root"
PASS = "mindL4786%@qq"

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS)

def run(cmd, desc=""):
    if desc: print(f"\n>>> {desc}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=60)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out: print(out.strip())
    if err: print(err.strip(), end=" ")
    return out + err

# Step 1: Update system and install dependencies
run("apt-get update -qq && apt-get install -y -qq python3-pip git nginx 2>&1 | tail -3", "安装 Python/Git/Nginx")

# Step 2: Clone repo
run("rm -rf /opt/diagram-to-music 2>/dev/null; git clone https://github.com/mindmapmaster/diagram-to-music.git /opt/diagram-to-music", "克隆代码")

# Step 3: Install Python deps
run("pip3 install flask requests gunicorn 2>&1 | tail -3", "安装 Python 依赖")

# Step 4: Create systemd service
service_config = """[Unit]
Description=Diagram to Music Flask App
After=network.target

[Service]
User=root
WorkingDirectory=/opt/diagram-to-music
Environment="MINIMAX_API_KEY=sk-cp-qg1lWPpYimwyOcvGKm5GkhS6vhPVFAZKFbEvUvEy3QvVt1btbUYUF49fnyBfr6pVQgQ3QhsLBm70z3FtJ4GJJ0Gs-mrxgf9ekxNq5wSvmWkEMZJ9J79bMhg"
Environment="ZHIPU_API_KEY=d13f82b5de734bd6a288da3265a2fd85.FlBWkvIcIjotr0Ww"
ExecStart=/usr/bin/gunicorn app:app --bind 0.0.0.0:5001 --workers 2 --timeout 120
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

sftp = ssh.open_sftp()
with sftp.file("/etc/systemd/system/diagram-to-music.service", "w") as f:
    f.write(service_config)
sftp.close()

# Step 5: Start service
run("systemctl daemon-reload && systemctl enable diagram-to-music && systemctl restart diagram-to-music", "启动服务")
time.sleep(3)
run("systemctl status diagram-to-music --no-pager -l | head -10", "检查状态")

# Step 6: Verify
run("curl -s http://localhost:5001/api/health", "验证接口")

print("\n✅ 部署完成！")
print(f"访问地址: http://{HOST}:5001")
print(f"健康检查: curl http://{HOST}:5001/api/health")

ssh.close()
