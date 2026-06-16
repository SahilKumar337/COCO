import subprocess
import time
import sys
import os #inportant

print("=======================================================")
print("  SIFRA AI - HIGH AVAILABILITY WATCHDOG")
print("  Monitoring process for crashes and auto-restarting...")
print("=======================================================")

def start_server():
    while True:
        print("\n[Watchdog] Booting SIFRA Server Engine...")
        try:
            # Start the main server process
            process = subprocess.Popen([sys.executable, "server.py"])
            
            # Wait for the process to exit
            process.wait()
            
            # Check exit code
            if process.returncode == 0:
                print("\n[Watchdog] Server shut down gracefully. Exiting.")
                break
            else:
                print(f"\n[Watchdog] CRITICAL: Server crashed (Exit Code: {process.returncode})!")
                print("[Watchdog] Auto-Repair System engaged. Restarting in 3 seconds...")
                time.sleep(3)
                
        except KeyboardInterrupt:
            print("\n[Watchdog] Manual termination detected. Shutting down SIFRA...")
            try:
                process.terminate()
            except:
                pass
            break
        except Exception as e:
            print(f"\n[Watchdog] Fatal Watchdog Error: {e}")
            print("[Watchdog] Attempting recovery in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    start_server()
