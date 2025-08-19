#!/usr/bin/env python3
"""
Enhanced System Monitor for Multiple Devices
Exports CPU, Memory, and Network metrics to Prometheus
"""

import time
import psutil
import logging
import platform
import uuid
import subprocess
from prometheus_client import start_http_server, Gauge, Info
from collections import defaultdict
from typing import List, Dict, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Get device serial number
def get_device_serial():
    """Get device serial number"""
    try:
        if platform.system() == "Darwin":  # macOS
            result = subprocess.run(['system_profiler', 'SPHardwareDataType'], 
                                  capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'Serial Number' in line:
                    return line.split(':')[1].strip()
        elif platform.system() == "Linux":
            try:
                with open('/sys/class/dmi/id/product_serial', 'r') as f:
                    return f.read().strip()
            except:
                pass
        elif platform.system() == "Windows":
            result = subprocess.run(['wmic', 'bios', 'get', 'serialnumber'], 
                                  capture_output=True, text=True)
            lines = result.stdout.split('\n')
            for line in lines:
                if line.strip() and 'SerialNumber' not in line:
                    return line.strip()
    except Exception as e:
        logger.warning(f"Could not get device serial: {e}")
    
    # Fallback to MAC address hash
    mac = uuid.getnode()
    return f"MAC-{hex(mac)[2:].upper()}"

# Prometheus metrics with device_serial tag
# CPU Metrics
app_cpu_usage = Gauge(
    'app_cpu_usage_percent',
    'CPU usage percentage by application (top 10)',
    ['device_serial', 'app_name']
)

total_cpu_usage = Gauge(
    'total_cpu_usage_percent',
    'Total CPU usage percentage for all applications',
    ['device_serial']
)

# Memory Metrics  
app_memory_usage = Gauge(
    'app_memory_usage_mb',
    'Memory usage in MB by application (top 10)',
    ['device_serial', 'app_name']
)

total_memory_usage = Gauge(
    'total_memory_usage_percent',
    'Total memory usage percentage for all applications',
    ['device_serial']
)

# Network Metrics
app_network_usage = Gauge(
    'app_network_usage_mbps',
    'Network bandwidth usage in Mbps by application (top 10)',
    ['device_serial', 'app_name', 'direction']
)

total_network_usage = Gauge(
    'total_network_usage_mbps',
    'Total network bandwidth usage in Mbps',
    ['device_serial', 'direction']
)

# System info
system_info = Info(
    'system_info',
    'System information'
)

class EnhancedMonitor:
    def __init__(self, top_n: int = 10):
        self.top_n = top_n
        self.device_serial = get_device_serial()
        self.process_network_cache = {}
        self.previous_net_io = {}
        
        logger.info(f"Device Serial: {self.device_serial}")
        
        # Set system info
        system_info.info({
            'device_serial': self.device_serial,
            'platform': platform.system(),
            'cpu_count': str(psutil.cpu_count()),
            'memory_total_gb': str(round(psutil.virtual_memory().total / (1024**3), 2))
        })
        
    def get_process_info(self, proc: psutil.Process) -> Dict:
        """Get comprehensive process information"""
        try:
            with proc.oneshot():
                # Get basic info
                pid = proc.pid
                name = proc.name()
                cpu_percent = proc.cpu_percent()
                memory_mb = proc.memory_info().rss / (1024 * 1024)
                
                # Get network info (approximate by process connections)
                try:
                    connections = proc.connections()
                    net_sent = 0
                    net_recv = 0
                    
                    # This is a simplified approach - real per-process network monitoring
                    # would require more complex system-level tracking
                    if connections:
                        # Estimate based on number of connections and system network usage
                        sys_net = psutil.net_io_counters()
                        conn_count = len(connections)
                        if conn_count > 0:
                            # Simple heuristic: distribute network usage based on connection count
                            total_processes = len(list(psutil.process_iter()))
                            net_factor = conn_count / max(total_processes, 1)
                            
                            current_time = time.time()
                            if pid in self.previous_net_io:
                                prev_time, prev_sent, prev_recv = self.previous_net_io[pid]
                                time_diff = current_time - prev_time
                                if time_diff > 0:
                                    net_sent = max(0, (sys_net.bytes_sent - prev_sent) * net_factor / time_diff / 1024 / 1024 * 8)  # Mbps
                                    net_recv = max(0, (sys_net.bytes_recv - prev_recv) * net_factor / time_diff / 1024 / 1024 * 8)  # Mbps
                            
                            self.previous_net_io[pid] = (current_time, sys_net.bytes_sent, sys_net.bytes_recv)
                        
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    net_sent = net_recv = 0
                
                return {
                    'pid': pid,
                    'name': name,
                    'cpu_percent': cpu_percent,
                    'memory_mb': memory_mb,
                    'network_sent_mbps': net_sent,
                    'network_recv_mbps': net_recv
                }
                
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
            
    def get_top_processes(self) -> List[Dict]:
        """Get top N processes by CPU usage"""
        processes = []
        
        # Get all processes
        for proc in psutil.process_iter():
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
        """Update all Prometheus metrics"""
        try:
            # Get top processes
            top_processes = self.get_top_processes()
            
            # Clear previous metrics
            app_cpu_usage.clear()
            app_memory_usage.clear()
            app_network_usage.clear()
            
            # Calculate totals
            total_cpu = 0
            total_memory_used = 0
            total_net_sent = 0
            total_net_recv = 0
            
            # Update metrics for top processes
            for proc_info in top_processes:
                app_name = proc_info['name']
                cpu_percent = proc_info['cpu_percent']
                memory_mb = proc_info['memory_mb']
                net_sent = proc_info['network_sent_mbps']
                net_recv = proc_info['network_recv_mbps']
                
                # CPU metrics (without PID, with device_serial)
                app_cpu_usage.labels(
                    device_serial=self.device_serial,
                    app_name=app_name
                ).set(cpu_percent)
                
                # Memory metrics
                app_memory_usage.labels(
                    device_serial=self.device_serial,
                    app_name=app_name
                ).set(memory_mb)
                
                # Network metrics
                if net_sent > 0:
                    app_network_usage.labels(
                        device_serial=self.device_serial,
                        app_name=app_name,
                        direction='sent'
                    ).set(net_sent)
                
                if net_recv > 0:
                    app_network_usage.labels(
                        device_serial=self.device_serial,
                        app_name=app_name,
                        direction='received'
                    ).set(net_recv)
                
                # Accumulate totals
                total_cpu += cpu_percent
                total_memory_used += memory_mb
                total_net_sent += net_sent
                total_net_recv += net_recv
            
            # Update total metrics
            total_cpu_usage.labels(device_serial=self.device_serial).set(
                min(100.0, psutil.cpu_percent(interval=None))  # Use system CPU, cap at 100%
            )
            
            # Total memory percentage
            memory_info = psutil.virtual_memory()
            total_memory_usage.labels(device_serial=self.device_serial).set(memory_info.percent)
            
            # Total network usage
            net_io = psutil.net_io_counters()
            total_network_usage.labels(
                device_serial=self.device_serial, 
                direction='sent'
            ).set(total_net_sent)
            
            total_network_usage.labels(
                device_serial=self.device_serial, 
                direction='received'
            ).set(total_net_recv)
            
            logger.info(f"Updated metrics for {len(top_processes)} processes, CPU: {psutil.cpu_percent(interval=None):.1f}%, Memory: {memory_info.percent:.1f}%")
            
        except Exception as e:
            logger.error(f"Error updating metrics: {e}")
    
    def start_monitoring(self, port: int = 8001, interval: int = 1):
        """Start the monitoring service"""
        logger.info(f"Starting Enhanced Monitor on port {port}")
        logger.info(f"Device Serial: {self.device_serial}")
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
            logger.info("Shutting down Enhanced Monitor...")
        except Exception as e:
            logger.error(f"Unexpected error: {e}")

def main():
    """Main function"""
    monitor = EnhancedMonitor(top_n=10)
    monitor.start_monitoring(port=8001, interval=1)

if __name__ == "__main__":
    main()
