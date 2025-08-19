#!/usr/bin/env python3
"""
Push-based System Monitor for Multiple Devices
Pushes CPU, Memory, and Network metrics to Prometheus Pushgateway
"""

import time
import psutil
import logging
import platform
import uuid
import subprocess
import requests
import argparse
from prometheus_client import CollectorRegistry, Gauge, Info, push_to_gateway
from typing import Dict, List

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

class PushMonitor:
    def __init__(self, pushgateway_url: str, job_name: str = "device-metrics", top_n: int = 10):
        self.pushgateway_url = pushgateway_url
        self.job_name = job_name
        self.top_n = top_n
        self.device_serial = get_device_serial()
        self.previous_net_io = {}
        
        # Create separate registry for clean metrics
        self.registry = CollectorRegistry()
        
        logger.info(f"Device Serial: {self.device_serial}")
        logger.info(f"Pushgateway URL: {self.pushgateway_url}")
        
        # Define metrics with registry
        self.app_cpu_usage = Gauge(
            'app_cpu_usage_percent',
            'CPU usage percentage by application (top 10)',
            ['device_serial', 'app_name'],
            registry=self.registry
        )

        self.total_cpu_usage = Gauge(
            'total_cpu_usage_percent',
            'Total CPU usage percentage for all applications',
            ['device_serial'],
            registry=self.registry
        )

        self.app_memory_usage = Gauge(
            'app_memory_usage_mb',
            'Memory usage in MB by application (top 10)',
            ['device_serial', 'app_name'],
            registry=self.registry
        )

        self.total_memory_usage = Gauge(
            'total_memory_usage_percent',
            'Total memory usage percentage for all applications',
            ['device_serial'],
            registry=self.registry
        )

        self.app_network_usage = Gauge(
            'app_network_usage_mbps',
            'Network bandwidth usage in Mbps by application (top 10)',
            ['device_serial', 'app_name', 'direction'],
            registry=self.registry
        )

        self.total_network_usage = Gauge(
            'total_network_usage_mbps',
            'Total network bandwidth usage in Mbps',
            ['device_serial', 'direction'],
            registry=self.registry
        )

        self.system_info = Info(
            'system_info',
            'System information',
            registry=self.registry
        )
        
        # Set system info once
        self.system_info.info({
            'device_serial': self.device_serial,
            'platform': platform.system(),
            'cpu_count': str(psutil.cpu_count()),
            'memory_total_gb': str(round(psutil.virtual_memory().total / (1024**3), 2))
        })
        
    def get_process_info(self, proc: psutil.Process) -> Dict:
        """Get comprehensive process information"""
        try:
            with proc.oneshot():
                pid = proc.pid
                name = proc.name()
                cpu_percent = proc.cpu_percent()
                memory_mb = proc.memory_info().rss / (1024 * 1024)
                
                # Simplified network tracking
                try:
                    connections = proc.connections()
                    net_sent = 0
                    net_recv = 0
                    
                    if connections:
                        sys_net = psutil.net_io_counters()
                        conn_count = len(connections)
                        if conn_count > 0:
                            total_processes = len(list(psutil.process_iter()))
                            net_factor = conn_count / max(total_processes, 1)
                            
                            current_time = time.time()
                            if pid in self.previous_net_io:
                                prev_time, prev_sent, prev_recv = self.previous_net_io[pid]
                                time_diff = current_time - prev_time
                                if time_diff > 0:
                                    net_sent = max(0, (sys_net.bytes_sent - prev_sent) * net_factor / time_diff / 1024 / 1024 * 8)
                                    net_recv = max(0, (sys_net.bytes_recv - prev_recv) * net_factor / time_diff / 1024 / 1024 * 8)
                            
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
        
        for proc in psutil.process_iter():
            try:
                proc_info = self.get_process_info(proc)
                if proc_info and proc_info['cpu_percent'] > 0:
                    processes.append(proc_info)
            except Exception as e:
                logger.debug(f"Error getting process info: {e}")
                continue
                
        processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
        return processes[:self.top_n]
    
    def collect_and_push_metrics(self):
        """Collect metrics and push to Pushgateway"""
        try:
            # Clear previous metrics
            self.app_cpu_usage.clear()
            self.app_memory_usage.clear()
            self.app_network_usage.clear()
            
            # Get top processes
            top_processes = self.get_top_processes()
            
            total_net_sent = 0
            total_net_recv = 0
            
            # Update metrics for top processes
            for proc_info in top_processes:
                app_name = proc_info['name']
                cpu_percent = proc_info['cpu_percent']
                memory_mb = proc_info['memory_mb']
                net_sent = proc_info['network_sent_mbps']
                net_recv = proc_info['network_recv_mbps']
                
                # Set metrics
                self.app_cpu_usage.labels(
                    device_serial=self.device_serial,
                    app_name=app_name
                ).set(cpu_percent)
                
                self.app_memory_usage.labels(
                    device_serial=self.device_serial,
                    app_name=app_name
                ).set(memory_mb)
                
                if net_sent > 0:
                    self.app_network_usage.labels(
                        device_serial=self.device_serial,
                        app_name=app_name,
                        direction='sent'
                    ).set(net_sent)
                
                if net_recv > 0:
                    self.app_network_usage.labels(
                        device_serial=self.device_serial,
                        app_name=app_name,
                        direction='received'
                    ).set(net_recv)
                
                total_net_sent += net_sent
                total_net_recv += net_recv
            
            # Update total metrics
            self.total_cpu_usage.labels(device_serial=self.device_serial).set(
                min(100.0, psutil.cpu_percent(interval=None))
            )
            
            memory_info = psutil.virtual_memory()
            self.total_memory_usage.labels(device_serial=self.device_serial).set(memory_info.percent)
            
            self.total_network_usage.labels(
                device_serial=self.device_serial, 
                direction='sent'
            ).set(total_net_sent)
            
            self.total_network_usage.labels(
                device_serial=self.device_serial, 
                direction='received'
            ).set(total_net_recv)
            
            # Push to Pushgateway
            gateway_host_port = self.pushgateway_url.replace('http://', '').replace('https://', '')
            
            push_to_gateway(
                gateway_host_port,
                job=self.job_name,
                registry=self.registry,
                grouping_key={'device_serial': self.device_serial}
            )
            
            logger.info(f"✅ Pushed metrics for {len(top_processes)} processes | CPU: {psutil.cpu_percent(interval=None):.1f}% | Memory: {memory_info.percent:.1f}%")
            
        except Exception as e:
            logger.error(f"❌ Error collecting/pushing metrics: {e}")
    
    def start_monitoring(self, interval: int = 1):
        """Start the push-based monitoring"""
        logger.info(f"🚀 Starting Push-based Monitor")
        logger.info(f"📡 Device Serial: {self.device_serial}")
        logger.info(f"🔄 Push Interval: {interval} second(s)")
        logger.info(f"📊 Monitoring top {self.top_n} processes")
        logger.info(f"🎯 Pushgateway: {self.pushgateway_url}")
        
        # Test pushgateway connectivity
        try:
            response = requests.get(f"{self.pushgateway_url}/metrics", timeout=5)
            if response.status_code == 200:
                logger.info("✅ Pushgateway connectivity verified")
            else:
                logger.warning(f"⚠️  Pushgateway returned status {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Cannot connect to Pushgateway: {e}")
            logger.info("🔄 Will continue trying to push metrics...")
        
        # Initial CPU percent call to initialize
        psutil.cpu_percent(interval=None)
        
        try:
            while True:
                self.collect_and_push_metrics()
                time.sleep(interval)
                
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down Push Monitor...")
        except Exception as e:
            logger.error(f"💥 Unexpected error: {e}")

def main():
    """Main function with command line arguments"""
    parser = argparse.ArgumentParser(description='Push-based System Monitor')
    parser.add_argument(
        '--pushgateway', 
        default='http://localhost:9091',
        help='Pushgateway URL (default: http://localhost:9091)'
    )
    parser.add_argument(
        '--interval', 
        type=int, 
        default=1,
        help='Push interval in seconds (default: 1)'
    )
    parser.add_argument(
        '--job', 
        default='device-metrics',
        help='Job name for metrics (default: device-metrics)'
    )
    parser.add_argument(
        '--top-n', 
        type=int, 
        default=10,
        help='Number of top processes to monitor (default: 10)'
    )
    
    args = parser.parse_args()
    
    monitor = PushMonitor(
        pushgateway_url=args.pushgateway,
        job_name=args.job,
        top_n=args.top_n
    )
    
    monitor.start_monitoring(interval=args.interval)

if __name__ == "__main__":
    main()
