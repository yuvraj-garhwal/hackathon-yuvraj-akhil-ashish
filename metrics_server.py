#!/usr/bin/env python3
"""
Custom HTTP Metrics Server
Replaces Pushgateway with a lightweight, custom solution for collecting device metrics.

This server:
1. Receives metrics from devices via HTTP POST
2. Stores metrics in memory with timestamps
3. Exposes /metrics endpoint for Prometheus scraping
4. Handles metric expiration and cleanup
"""

import threading
import time
import json
import logging
import requests
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("metrics_server.log"),
    ],
)
logger = logging.getLogger(__name__)


@dataclass
class MetricValue:
    """Represents a single metric value with metadata"""

    name: str
    value: float
    labels: Dict[str, str]
    timestamp: datetime
    help_text: str = ""
    metric_type: str = "gauge"


class MetricsRegistry:
    """Thread-safe metrics storage and management"""

    def __init__(self, ttl_seconds: int = 300):
        """
        Initialize metrics registry

        Args:
            ttl_seconds: Time-to-live for metrics in seconds (default: 5 minutes)
        """
        self.metrics: Dict[str, List[MetricValue]] = {}
        self.ttl_seconds = ttl_seconds
        self._lock = threading.RLock()

        # Start cleanup thread
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()

        logger.info(f"📊 Metrics registry initialized with TTL: {ttl_seconds}s")

    def add_metric(self, metric: MetricValue) -> None:
        """Add or update a metric in the registry"""
        with self._lock:
            if metric.name not in self.metrics:
                self.metrics[metric.name] = []

            # Remove existing metric with same labels
            self.metrics[metric.name] = [
                m for m in self.metrics[metric.name] if m.labels != metric.labels
            ]

            # Add new metric
            self.metrics[metric.name].append(metric)

        logger.debug(f"✅ Added metric: {metric.name} = {metric.value}")

    def get_prometheus_format(self) -> str:
        """Export all metrics in Prometheus format"""
        with self._lock:
            lines = []

            for metric_name, metric_list in self.metrics.items():
                if not metric_list:
                    continue

                # Add help and type comments
                help_text = metric_list[0].help_text
                metric_type = metric_list[0].metric_type

                if help_text:
                    lines.append(f"# HELP {metric_name} {help_text}")
                lines.append(f"# TYPE {metric_name} {metric_type}")

                # Add metric values
                for metric in metric_list:
                    if self._is_metric_expired(metric):
                        continue

                    labels_str = ""
                    if metric.labels:
                        label_pairs = [f'{k}="{v}"' for k, v in metric.labels.items()]
                        labels_str = "{" + ",".join(label_pairs) + "}"

                    timestamp_ms = int(metric.timestamp.timestamp() * 1000)
                    lines.append(
                        f"{metric_name}{labels_str} {metric.value} {timestamp_ms}"
                    )

            return "\n".join(lines) + "\n"

    def get_metrics_count(self) -> Dict[str, int]:
        """Get count of metrics by name"""
        with self._lock:
            return {
                name: len([m for m in metrics if not self._is_metric_expired(m)])
                for name, metrics in self.metrics.items()
            }

    def _is_metric_expired(self, metric: MetricValue) -> bool:
        """Check if a metric has expired"""
        return datetime.now() - metric.timestamp > timedelta(seconds=self.ttl_seconds)

    def _cleanup_loop(self) -> None:
        """Background thread to cleanup expired metrics"""
        while True:
            try:
                with self._lock:
                    for metric_name in list(self.metrics.keys()):
                        self.metrics[metric_name] = [
                            m
                            for m in self.metrics[metric_name]
                            if not self._is_metric_expired(m)
                        ]

                        # Remove empty metric lists
                        if not self.metrics[metric_name]:
                            del self.metrics[metric_name]

                time.sleep(60)  # Cleanup every minute

            except Exception as e:
                logger.error(f"❌ Error in cleanup loop: {e}")
                time.sleep(10)


class MetricsHandler(BaseHTTPRequestHandler):
    """HTTP request handler for metrics collection and serving"""

    def __init__(self, *args, registry: MetricsRegistry, **kwargs):
        self.registry = registry
        super().__init__(*args, **kwargs)

    def do_GET(self):
        """Handle GET requests"""
        try:
            path = urlparse(self.path).path

            if path == "/metrics":
                self._serve_metrics()
            elif path == "/health":
                self._serve_health()
            elif path == "/status":
                self._serve_status()
            elif path.startswith("/device-replacement/"):
                self._serve_device_replacement_check()
            else:
                self._send_error(404, "Not Found")

        except Exception as e:
            logger.error(f"❌ Error handling GET request: {e}")
            self._send_error(500, "Internal Server Error")

    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS preflight"""
        path = urlparse(self.path).path

        # Only handle CORS for device-replacement endpoint
        if path.startswith("/device-replacement/"):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "86400")  # 24 hours
            self.end_headers()
        else:
            self._send_error(404, "Not Found")

    def do_POST(self):
        """Handle POST requests for metric ingestion"""
        try:
            path = urlparse(self.path).path

            if path == "/metrics":
                self._ingest_metrics()
            else:
                self._send_error(404, "Not Found")

        except Exception as e:
            logger.error(f"❌ Error handling POST request: {e}")
            self._send_error(500, "Internal Server Error")

    def _serve_metrics(self):
        """Serve metrics in Prometheus format"""
        metrics_output = self.registry.get_prometheus_format()

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(metrics_output.encode("utf-8"))

        line_count = len(metrics_output.split("\n"))
        logger.debug(f"📊 Served {line_count} metric lines")

    def _serve_health(self):
        """Serve health check endpoint"""
        health_data = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "metrics_count": sum(self.registry.get_metrics_count().values()),
        }

        self._send_json_response(health_data)

    def _serve_status(self):
        """Serve detailed status information"""
        status_data = {
            "status": "running",
            "timestamp": datetime.now().isoformat(),
            "metrics_by_name": self.registry.get_metrics_count(),
            "ttl_seconds": self.registry.ttl_seconds,
            "total_metrics": sum(self.registry.get_metrics_count().values()),
        }

        self._send_json_response(status_data)

    def _serve_device_replacement_check(self):
        """Check if device needs replacement based on CPU/Memory thresholds"""
        try:
            # Extract device serial from URL path
            path = urlparse(self.path).path
            device_serial = path.split("/")[-1] if path.split("/")[-1] else None

            if not device_serial:
                self._send_error_with_cors(
                    400, "Device serial number required in URL path"
                )
                return

            # Configuration - Tunable thresholds and time windows
            # TODO: Make these configurable via environment variables or config file
            CPU_HIGH_THRESHOLD = 80.0  # High CPU threshold (%)
            CPU_LOW_THRESHOLD = (
                5.0  # Low CPU threshold (%) - indicates device may be underutilized
            )
            MEMORY_HIGH_THRESHOLD = 85.0  # High memory threshold (%)
            MEMORY_LOW_THRESHOLD = (
                10.0  # Low memory threshold (%) - indicates potential issues
            )
            TIME_WINDOW_MINUTES = 10  # Time window for averaging (minutes)
            PROMETHEUS_URL = (
                "http://prometheus:9090"  # Prometheus URL (adjust if needed)
            )

            replacement_needed = False
            reasons = []
            metrics_data = {}

            try:
                # Query Prometheus for average CPU usage over the last X minutes
                cpu_query = f'avg_over_time(total_cpu_usage_percent{{device_serial="{device_serial}"}}[{TIME_WINDOW_MINUTES}m])'
                cpu_response = requests.get(
                    f"{PROMETHEUS_URL}/api/v1/query",
                    params={"query": cpu_query},
                    timeout=5,
                )

                if cpu_response.status_code == 200:
                    cpu_data = cpu_response.json()
                    if cpu_data.get("status") == "success" and cpu_data.get(
                        "data", {}
                    ).get("result"):
                        avg_cpu = float(cpu_data["data"]["result"][0]["value"][1])
                        metrics_data["avg_cpu"] = avg_cpu

                        # Check CPU thresholds
                        if avg_cpu >= CPU_HIGH_THRESHOLD:
                            replacement_needed = True
                            reasons.append(
                                f"High CPU usage: {avg_cpu:.1f}% (threshold: {CPU_HIGH_THRESHOLD}%)"
                            )
                        elif avg_cpu <= CPU_LOW_THRESHOLD:
                            replacement_needed = True
                            reasons.append(
                                f"Unusually low CPU usage: {avg_cpu:.1f}% (threshold: {CPU_LOW_THRESHOLD}%)"
                            )

                # Query Prometheus for average Memory usage over the last X minutes
                memory_query = f'avg_over_time(total_memory_usage_percent{{device_serial="{device_serial}"}}[{TIME_WINDOW_MINUTES}m])'
                memory_response = requests.get(
                    f"{PROMETHEUS_URL}/api/v1/query",
                    params={"query": memory_query},
                    timeout=5,
                )

                if memory_response.status_code == 200:
                    memory_data = memory_response.json()
                    if memory_data.get("status") == "success" and memory_data.get(
                        "data", {}
                    ).get("result"):
                        avg_memory = float(memory_data["data"]["result"][0]["value"][1])
                        metrics_data["avg_memory"] = avg_memory

                        # Check Memory thresholds
                        if avg_memory >= MEMORY_HIGH_THRESHOLD:
                            replacement_needed = True
                            reasons.append(
                                f"High memory usage: {avg_memory:.1f}% (threshold: {MEMORY_HIGH_THRESHOLD}%)"
                            )
                        elif avg_memory <= MEMORY_LOW_THRESHOLD:
                            replacement_needed = True
                            reasons.append(
                                f"Unusually low memory usage: {avg_memory:.1f}% (threshold: {MEMORY_LOW_THRESHOLD}%)"
                            )

                # Optional: Query for network anomalies (commented out for now)
                # network_query = f"avg_over_time(total_network_usage_mbps{{device_serial=\"{device_serial}\"}}[{TIME_WINDOW_MINUTES}m])"
                # This could be extended to check for network-related replacement indicators

            except requests.RequestException as e:
                logger.warning(f"⚠️ Could not connect to Prometheus: {e}")
                # Fallback to current metrics in our registry if Prometheus is unavailable
                replacement_needed = self._check_current_metrics_fallback(device_serial)
                reasons.append("Used current metrics (Prometheus unavailable)")

            # Prepare response
            response_data = {
                "replace_device": replacement_needed,
                "device_serial": device_serial,
                "timestamp": datetime.now().isoformat(),
                "analysis_window_minutes": TIME_WINDOW_MINUTES,
                "thresholds": {
                    "cpu_high": CPU_HIGH_THRESHOLD,
                    "cpu_low": CPU_LOW_THRESHOLD,
                    "memory_high": MEMORY_HIGH_THRESHOLD,
                    "memory_low": MEMORY_LOW_THRESHOLD,
                },
                "metrics": metrics_data,
                "reasons": reasons,
            }

            self._send_json_response_with_cors(response_data)

            # Log the recommendation
            status_emoji = "🔴" if replacement_needed else "✅"
            logger.info(
                f"{status_emoji} Device replacement check for {device_serial}: {replacement_needed}"
            )
            if reasons:
                logger.info(f"📋 Reasons: {', '.join(reasons)}")

        except Exception as e:
            logger.error(f"❌ Error in device replacement check: {e}")
            self._send_error_with_cors(500, "Internal Server Error")

    def _check_current_metrics_fallback(self, device_serial: str) -> bool:
        """Fallback method to check current metrics when Prometheus is unavailable"""
        try:
            # Check current metrics in our registry
            with self.registry._lock:
                # Look for recent CPU metrics
                cpu_metrics = self.registry.metrics.get("total_cpu_usage_percent", [])
                memory_metrics = self.registry.metrics.get(
                    "total_memory_usage_percent", []
                )

                current_time = datetime.now()
                recent_threshold = timedelta(
                    minutes=2
                )  # Only consider metrics from last 2 minutes

                # Check CPU
                for metric in cpu_metrics:
                    if (
                        metric.labels.get("device_serial") == device_serial
                        and current_time - metric.timestamp < recent_threshold
                    ):
                        if metric.value >= 80.0 or metric.value <= 5.0:
                            return True

                # Check Memory
                for metric in memory_metrics:
                    if (
                        metric.labels.get("device_serial") == device_serial
                        and current_time - metric.timestamp < recent_threshold
                    ):
                        if metric.value >= 85.0 or metric.value <= 10.0:
                            return True

                return False
        except Exception as e:
            logger.error(f"❌ Error in fallback metrics check: {e}")
            return False

    def _ingest_metrics(self):
        """Ingest metrics from device POST requests"""
        try:
            # Read request body
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._send_error(400, "Empty request body")
                return

            body = self.rfile.read(content_length)
            data = json.loads(body.decode("utf-8"))

            # Validate request format
            if not isinstance(data, dict) or "metrics" not in data:
                self._send_error(
                    400, "Invalid request format. Expected: {'metrics': [...]}"
                )
                return

            # Process metrics
            device_serial = data.get("device_serial", "unknown")
            job_name = data.get("job", "device-metrics")
            timestamp = datetime.now()

            processed_count = 0
            for metric_data in data["metrics"]:
                try:
                    # Create metric object
                    labels = metric_data.get("labels", {})
                    labels["device_serial"] = device_serial
                    labels["job"] = job_name

                    metric = MetricValue(
                        name=metric_data["name"],
                        value=float(metric_data["value"]),
                        labels=labels,
                        timestamp=timestamp,
                        help_text=metric_data.get("help", ""),
                        metric_type=metric_data.get("type", "gauge"),
                    )

                    self.registry.add_metric(metric)
                    processed_count += 1

                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(f"⚠️ Skipping invalid metric: {e}")
                    continue

            # Send response
            response_data = {
                "status": "success",
                "processed_metrics": processed_count,
                "device_serial": device_serial,
                "timestamp": timestamp.isoformat(),
            }

            self._send_json_response(response_data)

            logger.info(
                f"✅ Processed {processed_count} metrics from device {device_serial}"
            )

        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON format")
        except Exception as e:
            logger.error(f"❌ Error ingesting metrics: {e}")
            self._send_error(500, "Internal Server Error")

    def _send_json_response(self, data: Dict[str, Any]):
        """Send JSON response"""
        response_body = json.dumps(data, indent=2)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response_body.encode("utf-8"))

    def _send_error(self, code: int, message: str):
        """Send error response"""
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(message.encode("utf-8"))

    def _send_json_response_with_cors(self, data: Dict[str, Any]):
        """Send JSON response with CORS headers"""
        response_body = json.dumps(data, indent=2)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(response_body.encode("utf-8"))

    def _send_error_with_cors(self, code: int, message: str):
        """Send error response with CORS headers"""
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(message.encode("utf-8"))

    def log_message(self, format, *args):
        """Override default logging to use our logger"""
        logger.debug(format % args)


class MetricsServer:
    """Custom metrics collection server"""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, ttl_seconds: int = 300):
        """
        Initialize metrics server

        Args:
            host: Server host (default: 0.0.0.0)
            port: Server port (default: 8080)
            ttl_seconds: Metric TTL in seconds (default: 300)
        """
        self.host = host
        self.port = port
        self.registry = MetricsRegistry(ttl_seconds)

        # Create handler class with registry
        def handler_factory(*args, **kwargs):
            return MetricsHandler(*args, registry=self.registry, **kwargs)

        self.server = HTTPServer((host, port), handler_factory)

        logger.info(f"🚀 Metrics server initialized at http://{host}:{port}")

    def start(self):
        """Start the metrics server"""
        try:
            logger.info(f"🌐 Starting metrics server on {self.host}:{self.port}")
            logger.info(f"📊 Endpoints available:")
            logger.info(f"   POST /metrics - Ingest metrics from devices")
            logger.info(f"   GET  /metrics - Prometheus scrape endpoint")
            logger.info(f"   GET  /health  - Health check")
            logger.info(f"   GET  /status  - Detailed status")

            self.server.serve_forever()

        except KeyboardInterrupt:
            logger.info("🛑 Received shutdown signal")
            self.stop()
        except Exception as e:
            logger.error(f"❌ Server error: {e}")
            raise

    def stop(self):
        """Stop the metrics server"""
        logger.info("🔴 Shutting down metrics server...")
        self.server.shutdown()
        self.server.server_close()
        logger.info("✅ Metrics server stopped")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Custom HTTP Metrics Server")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port", type=int, default=8080, help="Server port (default: 8080)"
    )
    parser.add_argument(
        "--ttl", type=int, default=300, help="Metric TTL in seconds (default: 300)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("🐛 Debug logging enabled")

    # Create and start server
    server = MetricsServer(args.host, args.port, args.ttl)

    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("👋 Goodbye!")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
