#!/usr/bin/env python3
"""
CPU Usage Monitor for Top 10 Applications
Exports metrics to Prometheus for Grafana visualization
"""

import time
import psutil
import logging
from prometheus_client import start_http_server, Gauge, Info
from collections import defaultdict
from typing import List, Dict, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Prometheus metrics
cpu_usage_gauge = Gauge(
    'app_cpu_usage_percent',
    'CPU usage percentage by application',
    ['app_name', 'pid']
)

memory_usage_gauge = Gauge(
    'app_memory_usage_mb',
    'Memory usage in MB by application',
    ['app_name', 'pid']
)

system_info = Info(
    'system_info',
    'System information'
)

total_cpu_gauge = Gauge(
    'system_total_cpu_percent',
    'Total system CPU usage percentage'
)

class CPUMonitor:
    def __init__(self, top_n: int = 10):
        self.top_n = top_n
        self.process_cache = {}
        self.previous_cpu_times = {}
        
        # Set system info
        system_info.info({
            'platform': psutil.platform,
            'cpu_count': str(psutil.cpu_count()),
            'memory_total_gb': str(round(psutil.virtual_memory().total / (1024**3), 2))
        })
        
    def get_process_info(self, proc: psutil.Process) -> Dict:
        """Get process information safely"""
        try:
            with proc.oneshot():
                info = {
                    'pid': proc.pid,
                    'name': proc.name(),
                    'cpu_percent': proc.cpu_percent(),
                    'memory_mb': proc.memory_info().rss / (1024 * 1024)
                }
                return info
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
            
    def get_top_cpu_processes(self) -> List[Dict]:
        """Get top N processes by CPU usage"""
        processes = []
        
        # Get all processes
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                proc_info = self.get_process_info(proc)
                if proc_info and proc_info['cpu_percent'] > 0:
                    processes.append(proc_info)
            except Exception as e:
                logger.debug(f"Error getting process info: {e}")
                continue
                
        # Sort by CPU usage and get top N
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
        return processes[:self.top_n]
    
    def update_metrics(self):
        """Update Prometheus metrics"""
        try:
            # Get top CPU processes
            top_processes = self.get_top_cpu_processes()
            
            # Clear previous metrics
            cpu_usage_gauge.clear()
            memory_usage_gauge.clear()
            
            # Update metrics for top processes
            for proc_info in top_processes:
                app_name = proc_info['name']
                pid = str(proc_info['pid'])
                cpu_percent = proc_info['cpu_percent']
                memory_mb = proc_info['memory_mb']
                
                cpu_usage_gauge.labels(app_name=app_name, pid=pid).set(cpu_percent)
                memory_usage_gauge.labels(app_name=app_name, pid=pid).set(memory_mb)
                
            # Update total system CPU
            total_cpu_gauge.set(psutil.cpu_percent(interval=None))
            
            logger.info(f"Updated metrics for {len(top_processes)} processes")
            
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
    
    def start_monitoring(self, port: int = 8000, interval: int = 1):
        """Start the monitoring service"""
        logger.info(f"Starting CPU monitor on port {port}")
        logger.info(f"Monitoring top {self.top_n} processes every {interval} second(s)")
        
        # Start Prometheus HTTP server
        start_http_server(port)
        logger.info(f"Prometheus metrics server started on http://localhost:{port}/metrics")
        
        # Initial CPU percent call to initialize
        psutil.cpu_percent(interval=None)
        
        try:
            while True:
                self.update_metrics()
                time.sleep(interval)
                
        except KeyboardInterrupt:
            logger.info("Shutting down CPU monitor...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

def main():
    """Main function"""
    monitor = CPUMonitor(top_n=10)
    monitor.start_monitoring(port=8000, interval=1)

if __name__ == "__main__":
    main()
