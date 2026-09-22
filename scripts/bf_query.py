import sys, time, subprocess
sys.path.insert(0, "/work/elodin-sim-aigp/scripts")
import configure_betaflight as c
subprocess.run(["pkill","-9","-f","betaflight_SITL"], capture_output=True); time.sleep(0.5)
bf = subprocess.Popen([str(c.BF_BINARY)], stdout=open("/tmp/bf.log","w"), stderr=subprocess.STDOUT, cwd=str(c.REPO_ROOT))
time.sleep(3.0)
cli = c.CLIClient("127.0.0.1", 5761)
cli.send(b"#\n"); print(cli.drain(1.0)[-200:])
for cmd in ("status", "aux", "get small_angle", "get angle_limit", "get acc_hardware", "feature", "get mode_range_logic", "version", "map"):
    cli.send((cmd + "\n").encode()); out = cli.drain(0.8)
    print("=== " + cmd); print(out.strip()[:900])
cli.close(); bf.kill()
