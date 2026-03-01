import subprocess
print(subprocess.run(["python3", "infrastructure/local_cli.py"], input="/cstat\n/ideas\n0\nexit\n", text=True, capture_output=True).stdout)
