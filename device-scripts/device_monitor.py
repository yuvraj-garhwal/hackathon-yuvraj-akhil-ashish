#!/usr/bin/env python3
"""
Device Monitor for Custom Metrics Server
Collects CPU, Memory, and Network metrics and sends them to a custom HTTP metrics server
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
import json
from queue import Queue
from collections import defaultdict, deque
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    
    # Fallback: use MAC address
    try:
        mac = uuid.getnode()
        return f"MAC-{hex(mac)[2:].upper()}"
    except:
        return "UNKNOWN"

class MetricsBatch:
    """Stores and aggregates metrics for batched sending"""
    
    def __init__(self):
        self.metrics: Dict[str, List[float]] = defaultdict(list)
        self.labels: Dict[str, Dict[str, str]] = {}
        self.help_texts: Dict[str, str] = {}
        self.types: Dict[str, str] = {}
        self.start_time = time.time()
    
    def add_metric(self, name: str, value: float, labels: Dict[str, str] = None, 
                   help_text: str = "", metric_type: str = "gauge"):
        """Add a metric to the batch"""
        metric_key = f"{name}_{json.dumps(labels or {}, sort_keys=True)}"
        self.metrics[metric_key].append(value)
        self.labels[metric_key] = labels or {}
        self.help_texts[name] = help_text
        self.types[name] = metric_type
    
    def get_aggregated_metrics(self, aggregation: str = "last") -> List[Dict[str, Any]]:
        """Get aggregated metrics ready for sending"""
        result = []
        
        for metric_key, values in self.metrics.items():
            if not values:
                continue
            
            # Extract name and labels
            parts = metric_key.split('_', 1)
            name_parts = []
            labels_json = "{}"
            
            for part in metric_key.split('_'):
                if part.startswith('{'):
                    labels_json = '_'.join(metric_key.split('_')[len(name_parts):])
                    break
                name_parts.append(part)
            
            name = '_'.join(name_parts)
            labels = self.labels.get(metric_key, {})
            
            # Aggregate values
            if aggregation == "last":
                value = values[-1]
            elif aggregation == "avg":
                value = sum(values) / len(values)
            elif aggregation == "max":
                value = max(values)
            elif aggregation == "min":
                value = min(values)
            else:
                value = values[-1]  # Default to last
            
            result.append({
                "name": name,
                "value": value,
                "labels": labels,
                "help": self.help_texts.get(name, ""),
                "type": self.types.get(name, "gauge")
            })
        
        return result
    
    def clear(self):
        """Clear all metrics from the batch"""
        self.metrics.clear()
        self.labels.clear()
        self.start_time = time.time()

class DeviceMonitor:
    """Device monitoring and metrics collection"""
    
    def __init__(self, device_serial: str, top_n: int = 10):
        self.device_serial = device_serial
        self.top_n = top_n
        self.previous_net_io = None
        self.boot_time = psutil.boot_time()
        
        logger.info(f"🔧 Device monitor initialized for {device_serial}")
    
    def collect_metrics(self) -> List[Dict[str, Any]]:
        """Collect all system metrics"""
        metrics = []
        
        try:
            # Collect CPU metrics
            cpu_metrics = self._collect_cpu_metrics()
            metrics.extend(cpu_metrics)
            
            # Collect memory metrics
            memory_metrics = self._collect_memory_metrics()
            metrics.extend(memory_metrics)
            
            # Collect network metrics
            network_metrics = self._collect_network_metrics()
            metrics.extend(network_metrics)
            
            # Add system info
            system_metrics = self._collect_system_info()
            metrics.extend(system_metrics)
            
        except Exception as e:
            logger.error(f"❌ Error collecting metrics: {e}")
        
        return metrics
    
    def _collect_cpu_metrics(self) -> List[Dict[str, Any]]:
        """Collect CPU usage metrics"""
        metrics = []
        
        try:
            # Get per-process CPU usage
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent']):
                try:
                    proc_info = proc.info
                    cpu_percent = proc_info.get('cpu_percent')
                    if cpu_percent is not None and cpu_percent > 0:
                        processes.append(proc_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError):
                    continue
            
            # Sort by CPU usage and get top N
            processes.sort(key=lambda x: x['cpu_percent'], reverse=True)
            top_processes = processes[:self.top_n]
            
            # CPU core count for normalization
            cpu_count = psutil.cpu_count()
            
            # Add per-app CPU metrics
            for proc in top_processes:
                app_name = proc['name']
                cpu_percent = proc['cpu_percent'] / cpu_count  # Normalize by CPU count
                
                metrics.append({
                    "name": "app_cpu_usage_percent",
                    "value": cpu_percent,
                    "labels": {
                        "app_name": app_name,
                        "device_serial": self.device_serial
                    },
                    "help": "CPU usage percentage by application (normalized by CPU count)",
                    "type": "gauge"
                })
            
            # Total CPU usage
            total_cpu = psutil.cpu_percent(interval=0.1)
            metrics.append({
                "name": "total_cpu_usage_percent",
                "value": total_cpu,
                "labels": {"device_serial": self.device_serial},
                "help": "Total system CPU usage percentage",
                "type": "gauge"
            })
            
        except Exception as e:
            logger.error(f"❌ Error collecting CPU metrics: {e}")
        
        return metrics
    
    def _collect_memory_metrics(self) -> List[Dict[str, Any]]:
        """Collect memory usage metrics"""
        metrics = []
        
        try:
            # Get per-process memory usage
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'memory_info']):
                try:
                    proc_info = proc.info
                    memory_info = proc_info.get('memory_info')
                    if memory_info is not None and hasattr(memory_info, 'rss'):
                        memory_mb = memory_info.rss / (1024 * 1024)
                        if memory_mb > 1:  # Only include processes using > 1MB
                            processes.append({
                                'name': proc_info['name'],
                                'memory_mb': memory_mb
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, AttributeError):
                    continue
            
            # Sort by memory usage and get top N
            processes.sort(key=lambda x: x['memory_mb'], reverse=True)
            top_processes = processes[:self.top_n]
            
            # Add per-app memory metrics
            for proc in top_processes:
                metrics.append({
                    "name": "app_memory_usage_mb",
                    "value": proc['memory_mb'],
                    "labels": {
                        "app_name": proc['name'],
                        "device_serial": self.device_serial
                    },
                    "help": "Memory usage in MB by application",
                    "type": "gauge"
                })
            
            # Total memory usage
            memory = psutil.virtual_memory()
            metrics.append({
                "name": "total_memory_usage_percent",
                "value": memory.percent,
                "labels": {"device_serial": self.device_serial},
                "help": "Total system memory usage percentage",
                "type": "gauge"
            })
            
        except Exception as e:
            logger.error(f"❌ Error collecting memory metrics: {e}")
        
        return metrics
    
    def _collect_network_metrics(self) -> List[Dict[str, Any]]:
        """Collect network usage metrics"""
        metrics = []
        
        try:
            # Get current network I/O
            current_net_io = psutil.net_io_counters(pernic=True)
            current_time = time.time()
            
            if self.previous_net_io is not None:
                time_delta = current_time - self.previous_time
                
                if time_delta > 0:
                    # Calculate total network usage
                    total_bytes_sent = 0
                    total_bytes_recv = 0
                    
                    for interface, current_stats in current_net_io.items():
                        if interface in self.previous_net_io:
                            prev_stats = self.previous_net_io[interface]
                            
                            bytes_sent = max(0, current_stats.bytes_sent - prev_stats.bytes_sent)
                            bytes_recv = max(0, current_stats.bytes_recv - prev_stats.bytes_recv)
                            
                            total_bytes_sent += bytes_sent
                            total_bytes_recv += bytes_recv
                    
                    # Convert to Mbps
                    mbps_sent = (total_bytes_sent * 8) / (time_delta * 1024 * 1024)
                    mbps_recv = (total_bytes_recv * 8) / (time_delta * 1024 * 1024)
                    
                    # Add total network metrics
                    metrics.extend([
                        {
                            "name": "total_network_usage_mbps",
                            "value": mbps_sent,
                            "labels": {
                                "device_serial": self.device_serial,
                                "direction": "sent"
                            },
                            "help": "Total network usage in Mbps",
                            "type": "gauge"
                        },
                        {
                            "name": "total_network_usage_mbps",
                            "value": mbps_recv,
                            "labels": {
                                "device_serial": self.device_serial,
                                "direction": "received"
                            },
                            "help": "Total network usage in Mbps",
                            "type": "gauge"
                        }
                    ])
                    
                    # Add per-app network metrics (simplified - using system total divided by number of network processes)
                    network_processes = []
                    for proc in psutil.process_iter(['pid', 'name']):
                        try:
                            # Get process object and check connections
                            process = psutil.Process(proc.info['pid'])
                            connections = process.connections()
                            if connections:
                                network_processes.append(proc.info['name'])
                        except (psutil.NoSuchProcess, psutil.AccessDenied, NotImplementedError, AttributeError):
                            continue
                    
                    # Get unique process names
                    unique_network_apps = list(set(network_processes))[:self.top_n]
                    
                    if unique_network_apps:
                        # Distribute network usage among active network processes
                        app_mbps_sent = mbps_sent / len(unique_network_apps)
                        app_mbps_recv = mbps_recv / len(unique_network_apps)
                        
                        for app_name in unique_network_apps:
                            metrics.extend([
                                {
                                    "name": "app_network_usage_mbps",
                                    "value": app_mbps_sent,
                                    "labels": {
                                        "app_name": app_name,
                                        "device_serial": self.device_serial,
                                        "direction": "sent"
                                    },
                                    "help": "Network usage in Mbps by application",
                                    "type": "gauge"
                                },
                                {
                                    "name": "app_network_usage_mbps",
                                    "value": app_mbps_recv,
                                    "labels": {
                                        "app_name": app_name,
                                        "device_serial": self.device_serial,
                                        "direction": "received"
                                    },
                                    "help": "Network usage in Mbps by application",
                                    "type": "gauge"
                                }
                            ])
            
            # Store current stats for next iteration
            self.previous_net_io = current_net_io
            self.previous_time = current_time
            
        except Exception as e:
            logger.error(f"❌ Error collecting network metrics: {e}")
        
        return metrics
    
    def _collect_system_info(self) -> List[Dict[str, Any]]:
        """Collect system information"""
        metrics = []
        
        try:
            # System info metric
            metrics.append({
                "name": "system_info_info",
                "value": 1,
                "labels": {
                    "device_serial": self.device_serial,
                    "platform": platform.system(),
                    "cpu_count": str(psutil.cpu_count()),
                    "hostname": platform.node()
                },
                "help": "System information",
                "type": "gauge"
            })
            
        except Exception as e:
            logger.error(f"❌ Error collecting system info: {e}")
        
        return metrics

class MetricsClient:
    """Client for sending metrics to custom metrics server"""
    
    def __init__(self, server_url: str, device_serial: str, job_name: str = "device-metrics"):
        self.server_url = server_url.rstrip('/')
        self.device_serial = device_serial
        self.job_name = job_name
        self.session = requests.Session()
        
        logger.info(f"📡 Metrics client initialized for {server_url}")
    
    def send_metrics(self, metrics: List[Dict[str, Any]]) -> bool:
        """Send metrics to the server"""
        try:
            payload = {
                "device_serial": self.device_serial,
                "job": self.job_name,
                "metrics": metrics,
                "timestamp": datetime.now().isoformat()
            }
            
            response = self.session.post(
                f"{self.server_url}/metrics",
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"}
            )
            
            response.raise_for_status()
            result = response.json()
            
            logger.debug(f"✅ Sent {result.get('processed_metrics', 0)} metrics successfully")
            return True
            
        except requests.RequestException as e:
            logger.error(f"❌ Error sending metrics: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error sending metrics: {e}")
            return False

class BatchDeviceMonitor:
    """Batch monitoring with configurable collection and push intervals"""
    
    def __init__(self, server_url: str, device_serial: str, top_n: int = 10,
                 collect_interval: float = 1.0, push_interval: float = 10.0,
                 aggregation: str = "last", job_name: str = "device-metrics"):
        
        self.monitor = DeviceMonitor(device_serial, top_n)
        self.client = MetricsClient(server_url, device_serial, job_name)
        self.collect_interval = collect_interval
        self.push_interval = push_interval
        self.aggregation = aggregation
        
        self.metrics_batch = MetricsBatch()
        self.running = False
        self.collect_thread = None
        self.push_thread = None
        
        logger.info(f"🚀 Batch monitor initialized:")
        logger.info(f"   📊 Device: {device_serial}")
        logger.info(f"   🔄 Collect interval: {collect_interval}s")
        logger.info(f"   📤 Push interval: {push_interval}s")
        logger.info(f"   📈 Aggregation: {aggregation}")
    
    def start(self):
        """Start the batch monitoring"""
        if self.running:
            logger.warning("⚠️ Monitor is already running")
            return
        
        self.running = True
        
        # Start collection thread
        self.collect_thread = threading.Thread(target=self._collect_loop, daemon=True)
        self.collect_thread.start()
        
        # Start push thread
        self.push_thread = threading.Thread(target=self._push_loop, daemon=True)
        self.push_thread.start()
        
        logger.info("🎯 Batch monitoring started")
        
        try:
            # Keep main thread alive
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("🛑 Received shutdown signal")
            self.stop()
    
    def stop(self):
        """Stop the batch monitoring"""
        logger.info("🔴 Stopping batch monitoring...")
        self.running = False
        
        if self.collect_thread:
            self.collect_thread.join(timeout=2)
        if self.push_thread:
            self.push_thread.join(timeout=2)
        
        logger.info("✅ Batch monitoring stopped")
    
    def _collect_loop(self):
        """Background collection loop"""
        logger.info(f"📊 Starting collection loop (interval: {self.collect_interval}s)")
        
        while self.running:
            try:
                start_time = time.time()
                
                # Collect metrics
                metrics = self.monitor.collect_metrics()
                
                # Add to batch
                for metric in metrics:
                    self.metrics_batch.add_metric(
                        metric["name"],
                        metric["value"],
                        metric["labels"],
                        metric["help"],
                        metric["type"]
                    )
                
                # Sleep for remaining time
                elapsed = time.time() - start_time
                sleep_time = max(0, self.collect_interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"❌ Error in collection loop: {e}")
                time.sleep(1)
    
    def _push_loop(self):
        """Background push loop"""
        logger.info(f"📤 Starting push loop (interval: {self.push_interval}s)")
        
        while self.running:
            try:
                time.sleep(self.push_interval)
                
                if not self.running:
                    break
                
                start_time = time.time()
                
                # Get aggregated metrics
                aggregated_metrics = self.metrics_batch.get_aggregated_metrics(self.aggregation)
                
                if aggregated_metrics:
                    # Send metrics
                    success = self.client.send_metrics(aggregated_metrics)
                    
                    if success:
                        duration = time.time() - start_time
                        logger.info(f"✅ Pushed batch: {len(aggregated_metrics)} metrics | "
                                  f"Duration: {duration:.2f}s | Aggregation: {self.aggregation}")
                        
                        # Clear batch after successful send
                        self.metrics_batch.clear()
                    else:
                        logger.warning("⚠️ Failed to push metrics, keeping in batch")
                else:
                    logger.debug("📭 No metrics to push")
                
            except Exception as e:
                logger.error(f"❌ Error in push loop: {e}")
                time.sleep(5)

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Device Monitor for Custom Metrics Server")
    parser.add_argument("--server-url", default="http://localhost:8080",
                        help="Metrics server URL (default: http://localhost:8080)")
    parser.add_argument("--collect-interval", type=float, default=1.0,
                        help="Metrics collection interval in seconds (default: 1.0)")
    parser.add_argument("--push-interval", type=float, default=10.0,
                        help="Metrics push interval in seconds (default: 10.0)")
    parser.add_argument("--aggregation", choices=["last", "avg", "max", "min"], default="last",
                        help="Aggregation method for batched metrics (default: last)")
    parser.add_argument("--top-n", type=int, default=10,
                        help="Number of top processes to monitor (default: 10)")
    parser.add_argument("--job", default="device-metrics",
                        help="Job name for metrics (default: device-metrics)")
    parser.add_argument("--device-serial", 
                        help="Override device serial number")
    parser.add_argument("--debug", action="store_true",
                        help="Enable debug logging")
    
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("🐛 Debug logging enabled")
    
    # Get device serial
    device_serial = args.device_serial or get_device_serial()
    
    logger.info(f"🎯 Device Monitor Starting")
    logger.info(f"   Device Serial: {device_serial}")
    logger.info(f"   Server URL: {args.server_url}")
    
    # Create and start monitor
    monitor = BatchDeviceMonitor(
        server_url=args.server_url,
        device_serial=device_serial,
        top_n=args.top_n,
        collect_interval=args.collect_interval,
        push_interval=args.push_interval,
        aggregation=args.aggregation,
        job_name=args.job
    )
    
    try:
        monitor.start()
    except KeyboardInterrupt:
        logger.info("👋 Goodbye!")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
