import paramiko
import time

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('pve01.knowledgeondemand.net', username='root', password='REDACTED', timeout=10)

# Fast ping sweep of entire /24
print("=== PING SWEEP INTERNAL_SUBNET ===")
cmd = '''
for i in $(seq 1 254); do
  (ping -c 1 -W 1 192.168.6.$i >/dev/null 2>&1 && echo "192.168.6.$i ALIVE") &
done
wait
'''
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
out = stdout.read().decode().strip()
if out:
    # Sort by IP
    lines = sorted(out.strip().split('\n'), key=lambda x: int(x.split('.')[3].split()[0]))
    for line in lines:
        print(line)

print()
ssh.close()
