# CPU Usage Monitor - Prometheus & Grafana PoC

This project monitors the CPU usage of the top 10 applications on your system in real-time, exports the metrics to Prometheus, and visualizes them in Grafana dashboards.

## Features

- **Real-time monitoring**: Updates every second
- **Top 10 applications**: Tracks the highest CPU-consuming processes
- **Prometheus metrics**: Exports CPU and memory usage metrics
- **Grafana visualization**: Beautiful dashboards with multiple chart types
- **Containerized**: Easy deployment with Docker Compose

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Python Script │───▶│   Prometheus    │───▶│     Grafana     │
│  (cpu_monitor)  │    │    (Port 9090)  │    │   (Port 3000)   │
│   Port 8000     │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Prerequisites

- Docker and Docker Compose
- Python 3.7+
- macOS/Linux system

## Quick Start

### 1. Clone and Navigate

```bash
cd /Users/yuvraj/Desktop/hackathon
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Start the Services

```bash
# Start Prometheus and Grafana containers
docker-compose up -d

# Wait for containers to be ready (30 seconds)
sleep 30
```

### 4. Start CPU Monitoring

```bash
# Run the CPU monitor script
python cpu_monitor.py
```

### 5. Access the Dashboards

- **Grafana**: http://localhost:3000
  - Username: `admin`
  - Password: `admin`
- **Prometheus**: http://localhost:9090
- **Metrics endpoint**: http://localhost:8000/metrics

## Dashboard Features

The Grafana dashboard includes:

1. **Real-time CPU Usage Chart**: Line chart showing CPU usage over time
2. **System Total CPU Gauge**: Current total system CPU usage
3. **CPU Distribution Pie Chart**: Visual distribution of CPU usage
4. **Memory Usage Chart**: Memory consumption by applications
5. **Current CPU Usage Bar Chart**: Instant view of current usage

## Metrics Available

### Application Metrics
- `app_cpu_usage_percent`: CPU usage percentage by application
- `app_memory_usage_mb`: Memory usage in MB by application

### System Metrics
- `system_total_cpu_percent`: Total system CPU usage
- `system_info`: System information (platform, CPU count, memory)

## Configuration

### Monitoring Interval
To change the monitoring interval, modify the `cpu_monitor.py` script:

```python
monitor.start_monitoring(port=8000, interval=1)  # Change interval here
```

### Number of Top Applications
To monitor more or fewer applications:

```python
monitor = CPUMonitor(top_n=10)  # Change top_n here
```

### Prometheus Scrape Interval
Edit `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'cpu-monitor'
    scrape_interval: 1s  # Change interval here
```

## Troubleshooting

### Common Issues

1. **Port conflicts**: Ensure ports 3000, 8000, and 9090 are free
2. **Permission issues**: Run with appropriate permissions for process monitoring
3. **Docker issues**: Ensure Docker is running and accessible

### Checking Services

```bash
# Check if containers are running
docker-compose ps

# Check container logs
docker-compose logs prometheus
docker-compose logs grafana

# Check Python script logs
# The script outputs logs to console
```

### Restarting Services

```bash
# Restart all services
docker-compose down
docker-compose up -d

# Restart just one service
docker-compose restart prometheus
docker-compose restart grafana
```

## Development

### Project Structure

```
hackathon/
├── cpu_monitor.py              # Main monitoring script
├── requirements.txt            # Python dependencies
├── docker-compose.yml          # Docker services
├── prometheus.yml              # Prometheus configuration
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/
│   │   │   └── datasource.yml  # Grafana datasource config
│   │   └── dashboards/
│   │       └── dashboard.yml   # Dashboard provisioning
│   └── dashboards/
│       └── cpu-dashboard.json  # Dashboard definition
└── README.md                   # This file
```

### Adding Custom Metrics

To add new metrics, modify `cpu_monitor.py`:

```python
# Add new Prometheus gauge
new_metric = Gauge('new_metric_name', 'Description', ['label1', 'label2'])

# Update in the monitoring loop
new_metric.labels(label1='value1', label2='value2').set(metric_value)
```

### Customizing Dashboards

1. Access Grafana at http://localhost:3000
2. Edit the existing dashboard or create new ones
3. Export the dashboard JSON
4. Replace the content in `grafana/dashboards/cpu-dashboard.json`

## Performance Considerations

- The script uses minimal CPU overhead (typically <1%)
- Memory usage is low (~10-20 MB)
- Network traffic is minimal for metrics export
- Data retention in Prometheus is set to 200 hours

## Security Notes

- Default Grafana credentials are admin/admin - change in production
- Prometheus metrics are exposed without authentication
- Consider firewall rules for production deployments

## Stopping the System

```bash
# Stop the Python script
# Press Ctrl+C in the terminal running cpu_monitor.py

# Stop Docker containers
docker-compose down

# Remove volumes (optional - deletes all data)
docker-compose down -v
```

## License

This project is for educational/PoC purposes.
