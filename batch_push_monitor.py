#!/usr/bin/env python3
"""
Batch Push-based System Monitor for Multiple Devices
Collects CPU, Memory, and Network metrics every second
Sends batched data to Prometheus Pushgateway at configurable intervals
"""

import time
import psutil
import logging
import platform
import uuid
import subprocess
import requests
import argparse
import threading
from queue import Queue
from collections import defaultdict, deque
from prometheus_client import CollectorRegistry, Gauge, Info, push_to_gateway
from typing import Dict, List, Optional
from datetime import datetime, timedelta

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

class MetricsBatch:
    """Class to store batched metrics data"""
    def __init__(self):
        self.metrics = defaultdict(list)
        self.timestamps = []
        self.batch_start = time.time()
    
    def add_metric(self, metric_name: str, value: float, labels: Dict[str, str], timestamp: float):
        """Add a metric to the batch"""
        self.metrics[metric_name].append({
            'value': value,
            'labels': labels,
            'timestamp': timestamp
        })
        if timestamp not in self.timestamps:
            self.timestamps.append(timestamp)
    
    def get_aggregated_metrics(self, aggregation_method: str = 'last') -> Dict:
        """Get aggregated metrics from the batch"""
        aggregated = {}
        
        for metric_name, metric_data in self.metrics.items():
            # Group by label combination
            label_groups = defaultdict(list)
            for data in metric_data:
                label_key = frozenset(data['labels'].items())
                label_groups[label_key].append(data)
            
            aggregated[metric_name] = {}
            for label_key, values in label_groups.items():
                labels = dict(label_key)
                
                if aggregation_method == 'last':
                    # Use the most recent value
                    latest = max(values, key=lambda x: x['timestamp'])
                    aggregated[metric_name][label_key] = {
                        'value': latest['value'],
                        'labels': labels
                    }
                elif aggregation_method == 'avg':
                    # Average all values in the batch
                    avg_value = sum(v['value'] for v in values) / len(values)
                    aggregated[metric_name][label_key] = {
                        'value': avg_value,
                        'labels': labels
                    }
                elif aggregation_method == 'max':
                    # Maximum value in the batch
                    max_value = max(v['value'] for v in values)
                    aggregated[metric_name][label_key] = {
                        'value': max_value,
                        'labels': labels
                    }
        
        return aggregated

class BatchPushMonitor:
    def __init__(self, pushgateway_url: str, job_name: str = "device-metrics", 
                 top_n: int = 10, collect_interval: int = 1, push_interval: int = 30,
                 aggregation_method: str = 'last'):
        self.pushgateway_url = pushgateway_url
        self.job_name = job_name
        self.top_n = top_n
        self.collect_interval = collect_interval
        self.push_interval = push_interval
        self.aggregation_method = aggregation_method
        self.device_serial = get_device_serial()
        self.previous_net_io = {}
        
        # Batching components
        self.current_batch = MetricsBatch()
        self.batch_lock = threading.Lock()
        self.metrics_queue = Queue()
        self.stop_event = threading.Event()
        
        # Create separate registry for clean metrics
        self.registry = CollectorRegistry()
        
        logger.info(f"Device Serial: {self.device_serial}")
        logger.info(f"Pushgateway URL: {self.pushgateway_url}")
        logger.info(f"Collect Interval: {self.collect_interval}s, Push Interval: {self.push_interval}s")
        logger.info(f"Aggregation Method: {self.aggregation_method}")
        
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
        
        # Batch metrics
        self.batch_info = Gauge(
            'batch_metrics_info',
            'Information about batched metrics',
            ['device_serial', 'metric_type'],
            registry=self.registry
        )
        
        # Set system info once
        self.system_info.info({
            'device_serial': self.device_serial,
            'platform': platform.system(),
            'cpu_count': str(psutil.cpu_count()),
            'memory_total_gb': str(round(psutil.virtual_memory().total / (1024**3), 2)),
            'collect_interval': str(self.collect_interval),
            'push_interval': str(self.push_interval),
            'aggregation_method': self.aggregation_method
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
    
    def collect_metrics(self):
        """Collect metrics and add to batch"""
        try:
            timestamp = time.time()
            top_processes = self.get_top_processes()
            
            total_net_sent = 0
            total_net_recv = 0
            
            with self.batch_lock:
                # Add process metrics to batch
                for proc_info in top_processes:
                    app_name = proc_info['name']
                    cpu_percent = proc_info['cpu_percent']
                    memory_mb = proc_info['memory_mb']
                    net_sent = proc_info['network_sent_mbps']
                    net_recv = proc_info['network_recv_mbps']
                    
                    # Add to batch
                    self.current_batch.add_metric(
                        'app_cpu_usage_percent',
                        cpu_percent,
                        {'device_serial': self.device_serial, 'app_name': app_name},
                        timestamp
                    )
                    
                    self.current_batch.add_metric(
                        'app_memory_usage_mb',
                        memory_mb,
                        {'device_serial': self.device_serial, 'app_name': app_name},
                        timestamp
                    )
                    
                    if net_sent > 0:
                        self.current_batch.add_metric(
                            'app_network_usage_mbps',
                            net_sent,
                            {'device_serial': self.device_serial, 'app_name': app_name, 'direction': 'sent'},
                            timestamp
                        )
                    
                    if net_recv > 0:
                        self.current_batch.add_metric(
                            'app_network_usage_mbps',
                            net_recv,
                            {'device_serial': self.device_serial, 'app_name': app_name, 'direction': 'received'},
                            timestamp
                        )
                    
                    total_net_sent += net_sent
                    total_net_recv += net_recv
                
                # Add total metrics
                self.current_batch.add_metric(
                    'total_cpu_usage_percent',
                    min(100.0, psutil.cpu_percent(interval=None)),
                    {'device_serial': self.device_serial},
                    timestamp
                )
                
                memory_info = psutil.virtual_memory()
                self.current_batch.add_metric(
                    'total_memory_usage_percent',
                    memory_info.percent,
                    {'device_serial': self.device_serial},
                    timestamp
                )
                
                self.current_batch.add_metric(
                    'total_network_usage_mbps',
                    total_net_sent,
                    {'device_serial': self.device_serial, 'direction': 'sent'},
                    timestamp
                )
                
                self.current_batch.add_metric(
                    'total_network_usage_mbps',
                    total_net_recv,
                    {'device_serial': self.device_serial, 'direction': 'received'},
                    timestamp
                )
            
            logger.debug(f"📊 Collected metrics for {len(top_processes)} processes at {datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')}")
            
        except Exception as e:
            logger.error(f"❌ Error collecting metrics: {e}")
    
    def push_batch(self):
        """Push the current batch to Pushgateway"""
        try:
            with self.batch_lock:
                if not self.current_batch.metrics:
                    logger.debug("🔄 No metrics to push")
                    return
                
                # Get aggregated metrics
                aggregated = self.current_batch.get_aggregated_metrics(self.aggregation_method)
                batch_size = len(self.current_batch.timestamps)
                batch_duration = time.time() - self.current_batch.batch_start
                
                # Clear registry and set aggregated values
                self.app_cpu_usage.clear()
                self.app_memory_usage.clear()
                self.app_network_usage.clear()
                
                metric_counts = defaultdict(int)
                
                # Apply aggregated metrics to Prometheus gauges
                for metric_name, metric_groups in aggregated.items():
                    for label_key, data in metric_groups.items():
                        labels = data['labels']
                        value = data['value']
                        metric_counts[metric_name] += 1
                        
                        if metric_name == 'app_cpu_usage_percent':
                            self.app_cpu_usage.labels(**labels).set(value)
                        elif metric_name == 'app_memory_usage_mb':
                            self.app_memory_usage.labels(**labels).set(value)
                        elif metric_name == 'app_network_usage_mbps':
                            self.app_network_usage.labels(**labels).set(value)
                        elif metric_name == 'total_cpu_usage_percent':
                            self.total_cpu_usage.labels(**labels).set(value)
                        elif metric_name == 'total_memory_usage_percent':
                            self.total_memory_usage.labels(**labels).set(value)
                        elif metric_name == 'total_network_usage_mbps':
                            self.total_network_usage.labels(**labels).set(value)
                
                # Set batch info metrics
                self.batch_info.labels(device_serial=self.device_serial, metric_type='batch_size').set(batch_size)
                self.batch_info.labels(device_serial=self.device_serial, metric_type='batch_duration_seconds').set(batch_duration)
                self.batch_info.labels(device_serial=self.device_serial, metric_type='metrics_count').set(sum(metric_counts.values()))
                
                # Reset batch
                self.current_batch = MetricsBatch()
            
            # Push to Pushgateway
            gateway_host_port = self.pushgateway_url.replace('http://', '').replace('https://', '')
            
            push_to_gateway(
                gateway_host_port,
                job=self.job_name,
                registry=self.registry,
                grouping_key={'device_serial': self.device_serial}
            )
            
            logger.info(f"🚀 Pushed batch: {batch_size} samples, {sum(metric_counts.values())} metrics, {batch_duration:.1f}s duration, aggregation: {self.aggregation_method}")
            
        except Exception as e:
            logger.error(f"❌ Error pushing batch: {e}")
    
    def collector_thread(self):
        """Thread function for collecting metrics"""
        logger.info(f"📊 Starting metrics collection (every {self.collect_interval}s)")
        
        # Initial CPU percent call to initialize
        psutil.cpu_percent(interval=None)
        
        while not self.stop_event.is_set():
            try:
                self.collect_metrics()
                time.sleep(self.collect_interval)
            except Exception as e:
                logger.error(f"❌ Error in collector thread: {e}")
                time.sleep(self.collect_interval)
    
    def pusher_thread(self):
        """Thread function for pushing batches"""
        logger.info(f"🚀 Starting batch pusher (every {self.push_interval}s)")
        
        while not self.stop_event.is_set():
            try:
                self.push_batch()
                time.sleep(self.push_interval)
            except Exception as e:
                logger.error(f"❌ Error in pusher thread: {e}")
                time.sleep(self.push_interval)
    
    def start_monitoring(self):
        """Start the batch-based monitoring"""
        logger.info(f"🎯 Starting Batch Push Monitor")
        logger.info(f"📡 Device Serial: {self.device_serial}")
        logger.info(f"📊 Collect Interval: {self.collect_interval}s")
        logger.info(f"🚀 Push Interval: {self.push_interval}s")
        logger.info(f"🔢 Aggregation: {self.aggregation_method}")
        logger.info(f"📈 Top Processes: {self.top_n}")
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
        
        # Start threads
        collector = threading.Thread(target=self.collector_thread, daemon=True)
        pusher = threading.Thread(target=self.pusher_thread, daemon=True)
        
        collector.start()
        pusher.start()
        
        try:
            # Keep main thread alive
            while True:
                time.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("🛑 Shutting down Batch Push Monitor...")
            self.stop_event.set()
            
            # Final push of remaining data
            logger.info("📤 Pushing final batch...")
            self.push_batch()
            
            logger.info("✅ Shutdown complete")

def main():
    """Main function with command line arguments"""
    parser = argparse.ArgumentParser(description='Batch Push-based System Monitor')
    parser.add_argument(
        '--pushgateway', 
        default='http://localhost:9091',
        help='Pushgateway URL (default: http://localhost:9091)'
    )
    parser.add_argument(
        '--collect-interval', 
        type=int, 
        default=1,
        help='Metrics collection interval in seconds (default: 1)'
    )
    parser.add_argument(
        '--push-interval', 
        type=int, 
        default=30,
        help='Batch push interval in seconds (default: 30)'
    )
    parser.add_argument(
        '--aggregation', 
        choices=['last', 'avg', 'max'],
        default='last',
        help='Aggregation method for batched metrics (default: last)'
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
    
    monitor = BatchPushMonitor(
        pushgateway_url=args.pushgateway,
        job_name=args.job,
        top_n=args.top_n,
        collect_interval=args.collect_interval,
        push_interval=args.push_interval,
        aggregation_method=args.aggregation
    )
    
    monitor.start_monitoring()

if __name__ == "__main__":
    main()
