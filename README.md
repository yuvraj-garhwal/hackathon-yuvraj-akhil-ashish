# 🚀 Device Monitoring System

A comprehensive system for monitoring CPU, Memory, and Network metrics from multiple devices using a custom HTTP metrics server, Prometheus, and Grafana.

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Device Script │───▶│ Metrics Server  │───▶│   Prometheus    │───▶│     Grafana     │
│  (Port: Client) │    │   (Port: 8080)  │    │   (Port: 9090)  │    │   (Port: 3000)  │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Components

- **Device Script**: Collects metrics from devices and pushes to metrics server
- **Metrics Server**: Custom HTTP server that receives and aggregates metrics
- **Prometheus**: Scrapes metrics from the metrics server for time-series storage
- **Grafana**: Visualizes metrics with comprehensive dashboards

## 📂 Project Structure

```
hackathon/
├── device-scripts/
│   └── device_monitor.py       # Device monitoring script
├── docker-compose.yml          # Docker services configuration
├── Dockerfile                  # Custom metrics server container
├── prometheus.yml              # Prometheus configuration
├── metrics_server.py           # Custom HTTP metrics server
├── enhanced-dashboard.json     # Grafana dashboard with network metrics
├── requirements.txt            # Python dependencies
└── README.md                   # This file
```

## 🚀 Quick Start

### 1. Start the Infrastructure

```bash
# Start all services (Prometheus, Grafana, Metrics Server)
docker-compose up -d

# Wait for services to be ready
sleep 30
```

### 2. Start Device Monitoring

```bash
# Install dependencies for device script
cd device-scripts
pip install -r ../requirements.txt

# Start monitoring (basic usage)
python3 device_monitor.py

# Advanced usage with custom intervals
python3 device_monitor.py \
  --server-url http://localhost:8080 \
  --collect-interval 1.0 \
  --push-interval 10.0 \
  --aggregation last \
  --top-n 10
```

### 3. Access Dashboards

- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090
- **Metrics Server**: http://localhost:8080/status

### 4. Import Dashboard

1. Go to Grafana → **"+"** → **"Import"**
2. Copy contents of `enhanced-dashboard.json`
3. Paste → **"Load"** → **"Import"**
4. Select your device from the dropdown

## ⚙️ Configuration

### Device Monitor Options

```bash
python3 device_monitor.py --help

Options:
  --server-url URL          Metrics server URL (default: http://localhost:8080)
  --collect-interval FLOAT  Collection interval in seconds (default: 1.0)
  --push-interval FLOAT     Push interval in seconds (default: 10.0)  
  --aggregation METHOD      Aggregation method: last|avg|max|min (default: last)
  --top-n INT              Number of top processes (default: 10)
  --job NAME               Job name for metrics (default: device-metrics)
  --device-serial ID       Override device serial number
  --debug                  Enable debug logging
```

### Metrics Server Options

```bash
python3 metrics_server.py --help

Options:
  --host HOST       Server host (default: 0.0.0.0)
  --port PORT       Server port (default: 8080)
  --ttl SECONDS     Metric TTL in seconds (default: 300)
  --debug           Enable debug logging
```

## 📊 Available Metrics

### Application Metrics
- `app_cpu_usage_percent`: CPU usage by application (normalized by CPU count)
- `app_memory_usage_mb`: Memory usage in MB by application  
- `app_network_usage_mbps`: Network usage in Mbps by application (sent/received)

### System Metrics
- `total_cpu_usage_percent`: Total system CPU usage
- `total_memory_usage_percent`: Total system memory usage
- `total_network_usage_mbps`: Total system network usage (sent/received)
- `system_info_info`: System information (platform, CPU count, hostname)

### Labels
- `device_serial`: Unique device identifier
- `app_name`: Application name
- `job`: Metrics job name
- `direction`: Network direction (sent/received)
- `platform`: Operating system
- `cpu_count`: Number of CPU cores
- `hostname`: Device hostname

## 🌐 Multi-Device Deployment

### Local Network Setup

```bash
# Start infrastructure on monitoring server
docker-compose up -d

# Device 1
python3 device_monitor.py --server-url http://192.168.1.100:8080 --job device1

# Device 2  
python3 device_monitor.py --server-url http://192.168.1.100:8080 --job device2

# Device 3
python3 device_monitor.py --server-url http://192.168.1.100:8080 --job device3
```

### Remote/Cloud Deployment

```bash
# Devices push to cloud metrics server
python3 device_monitor.py --server-url https://monitoring.yourcompany.com:8080
```

## 🔧 API Endpoints

### Metrics Server

- **POST `/metrics`**: Ingest metrics from devices
- **GET `/metrics`**: Prometheus scrape endpoint  
- **GET `/health`**: Health check
- **GET `/status`**: Detailed status information
- **GET `/device-replacement/{device_serial}`**: Check if device needs replacement based on CPU/Memory thresholds

### Sample POST Request

```json
{
  "device_serial": "GWHV4X1Y4L",
  "job": "device-metrics",
  "metrics": [
    {
      "name": "app_cpu_usage_percent",
      "value": 15.5,
      "labels": {
        "app_name": "Google Chrome",
        "device_serial": "GWHV4X1Y4L"
      },
      "help": "CPU usage percentage by application",
      "type": "gauge"
    }
  ]
}
```

### Device Replacement Check Endpoint

**GET `/device-replacement/{device_serial}`**

Analyzes device performance metrics to determine if replacement is recommended.

#### Usage:
```bash
curl http://localhost:8080/device-replacement/GWHV4X1Y4L
```

#### Response:
```json
{
  "replace_device": false,
  "device_serial": "GWHV4X1Y4L",
  "timestamp": "2025-08-20T08:45:05.253597",
  "analysis_window_minutes": 10,
  "thresholds": {
    "cpu_high": 80.0,
    "cpu_low": 5.0,
    "memory_high": 85.0,
    "memory_low": 10.0
  },
  "metrics": {
    "avg_cpu": 19.7,
    "avg_memory": 75.0
  },
  "reasons": []
}
```

#### Key Response Fields:
- **`replace_device`**: Boolean indicating if device replacement is recommended
- **`thresholds`**: Configurable thresholds used for analysis
- **`metrics`**: Average CPU and memory usage over analysis window
- **`reasons`**: List of reasons if replacement is recommended

#### Replacement Triggers:
- **High CPU**: Average > 80% over 10 minutes
- **Low CPU**: Average < 5% over 10 minutes (potential hardware issues)
- **High Memory**: Average > 85% over 10 minutes  
- **Low Memory**: Average < 10% over 10 minutes (potential issues)

#### Configuration:
Thresholds and time windows can be tuned in `metrics_server.py`:
```python
# Tunable parameters (lines 236-241)
CPU_HIGH_THRESHOLD = 80.0      # High CPU threshold (%)
CPU_LOW_THRESHOLD = 5.0        # Low CPU threshold (%)
MEMORY_HIGH_THRESHOLD = 85.0   # High memory threshold (%)
MEMORY_LOW_THRESHOLD = 10.0    # Low memory threshold (%)
TIME_WINDOW_MINUTES = 10       # Analysis time window (minutes)
```

## 📈 Dashboard Features

The enhanced dashboard includes:

### Real-time Gauges
- Total CPU usage (0-100%)
- Total memory usage (0-100%)  
- Network sent/received (bps)

### Time Series Charts
- Top 10 apps CPU usage over time
- Top 10 apps memory usage over time
- Top 10 apps network usage (sent/received)
- Total network traffic timeline

### Distribution Charts
- CPU usage pie chart
- Memory usage pie chart  
- Network usage pie chart
- Current usage bar charts

### Interactive Features
- Device serial dropdown for multi-device filtering
- Real-time updates (1-second refresh)
- Color-coded network directions (red=sent, blue=received)
- Auto-scaling units (K/M/G prefixes)

## 🔍 Troubleshooting

### Check Service Status

```bash
# Check all containers
docker-compose ps

# Check logs
docker-compose logs metrics-server
docker-compose logs prometheus
docker-compose logs grafana

# Check metrics server health
curl http://localhost:8080/health
curl http://localhost:8080/status
```

### Common Issues

1. **Port conflicts**: Ensure ports 3000, 8080, 9090 are free
2. **Device script errors**: Check network connectivity to metrics server
3. **No metrics in Grafana**: Verify Prometheus is scraping metrics server
4. **Dashboard not working**: Import `enhanced-dashboard.json` manually

### Restart Services

```bash
# Restart all services
docker-compose down && docker-compose up -d

# Restart specific service
docker-compose restart metrics-server
docker-compose restart prometheus
```

## 🔒 Security Considerations

- Default Grafana credentials: admin/admin (change in production)
- Metrics server has no authentication (add reverse proxy with auth for production)
- Consider firewall rules for production deployments
- Use HTTPS for remote deployments

## 🚦 Stopping the System

```bash
# Stop device monitoring
# Press Ctrl+C in device monitor terminal

# Stop infrastructure
docker-compose down

# Remove all data (optional)
docker-compose down -v
```

## 📝 License

This project is for educational/PoC purposes.