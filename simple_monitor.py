#!/usr/bin/env python3
"""
Simple CPU Monitor for testing
"""

import time
import psutil
from prometheus_client import start_http_server, Gauge

# Create metrics
cpu_gauge = Gauge('app_cpu_usage_percent', 'CPU usage percentage by application', ['app_name', 'pid'])
system_cpu_gauge = Gauge('system_total_cpu_percent', 'Total system CPU usage')

def get_top_processes(n=10):
    """Get top N processes by CPU usage"""
    processes = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            cpu_percent = proc.cpu_percent()
            if cpu_percent > 0:
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cpu_percent': cpu_percent
                })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
    return processes[:n]

def main():
    print("Starting simple CPU monitor...")
    
    # Start HTTP server
    start_http_server(8000)
    print("HTTP server started on port 8000")
    
    # Initial CPU measurement
    psutil.cpu_percent(interval=None)
    
    while True:
        try:
            # Clear previous metrics
            cpu_gauge.clear()
            
            # Get top processes
            top_processes = get_top_processes(10)
            print(f"Found {len(top_processes)} processes")
            
            # Update metrics
            for proc in top_processes:
                cpu_gauge.labels(app_name=proc['name'], pid=str(proc['pid'])).set(proc['cpu_percent'])
            
            # Update system CPU
            system_cpu_gauge.set(psutil.cpu_percent(interval=None))
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("Shutting down...")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
