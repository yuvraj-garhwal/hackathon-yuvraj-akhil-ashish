# 🚀 **Push-Based Monitoring Architecture**

## 🎯 **Architecture Overview**

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│    Device 1     │────▶│   Pushgateway   │◄────│   Prometheus    │────▶│     Grafana     │
│  push_monitor   │     │   (Port 9091)   │     │   (Port 9090)   │     │   (Port 3000)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
┌─────────────────┐            ▲
│    Device 2     │────────────┘
│  push_monitor   │
└─────────────────┘
┌─────────────────┐
│    Device N     │────────────┘
│  push_monitor   │
└─────────────────┘
```

**Data Flow:**
1. **Devices** run `push_monitor.py` and push metrics every 1-2 seconds
2. **Pushgateway** receives and stores the latest metrics from all devices  
3. **Prometheus** scrapes metrics from Pushgateway every 1 second
4. **Grafana** visualizes real-time data with device selection

---

## 🏗️ **Components**

### **1. Push Monitor (`push_monitor.py`)**
- Runs on each device/server
- Collects CPU, Memory, Network metrics
- Pushes to Pushgateway every N seconds (configurable)
- Handles device identification via serial number

### **2. Pushgateway (Port 9091)**
- Prometheus component for receiving pushed metrics
- Stores latest metric values from each device
- Provides HTTP endpoint for Prometheus to scrape

### **3. Prometheus (Port 9090)**
- Scrapes Pushgateway for aggregated metrics
- Stores time-series data
- Provides query API

### **4. Grafana (Port 3000)**
- Same dashboards work with pushed metrics
- Device serial dropdown for filtering
- Real-time visualization

---

## 🚀 **Quick Start**

### **1. Start Infrastructure**
```bash
cd /Users/yuvraj/Desktop/hackathon
docker-compose up -d
```

### **2. Run Push Monitor on Device**
```bash
# Basic usage (pushes every 1 second)
python3 push_monitor.py

# Custom interval (pushes every 5 seconds)
python3 push_monitor.py --interval 5

# Custom pushgateway URL (for remote server)
python3 push_monitor.py --pushgateway http://192.168.1.100:9091

# Custom job name and top-N processes
python3 push_monitor.py --job my-servers --top-n 15
```

### **3. Access Dashboards**
- **Grafana**: http://localhost:3000 (admin/admin)
- **Prometheus**: http://localhost:9090  
- **Pushgateway**: http://localhost:9091

---

## ⚙️ **Configuration Options**

### **Command Line Arguments**
```bash
python3 push_monitor.py --help

Options:
  --pushgateway URL    Pushgateway URL (default: http://localhost:9091)
  --interval SECONDS   Push interval in seconds (default: 1)
  --job NAME          Job name for metrics (default: device-metrics)
  --top-n NUMBER      Number of top processes (default: 10)
```

### **Environment Variables**
```bash
export PUSHGATEWAY_URL=http://monitoring-server:9091
export PUSH_INTERVAL=2
export DEVICE_JOB=production-servers
python3 push_monitor.py
```

---

## 🌐 **Multi-Device Deployment**

### **Scenario 1: Local Network**
```bash
# Server setup (run once)
docker-compose up -d

# Device 1
python3 push_monitor.py --pushgateway http://192.168.1.100:9091 --job device1

# Device 2  
python3 push_monitor.py --pushgateway http://192.168.1.100:9091 --job device2

# Device 3
python3 push_monitor.py --pushgateway http://192.168.1.100:9091 --job device3
```

### **Scenario 2: Cloud Deployment**
```bash
# Devices push to cloud Pushgateway
python3 push_monitor.py --pushgateway https://monitoring.yourcompany.com:9091
```

### **Scenario 3: Different Push Intervals**
```bash
# Critical servers (every 1 second)
python3 push_monitor.py --interval 1 --job critical-servers

# Regular servers (every 5 seconds)  
python3 push_monitor.py --interval 5 --job regular-servers

# Development machines (every 30 seconds)
python3 push_monitor.py --interval 30 --job dev-machines
```

---

## 📊 **Dashboard Queries (Updated)**

The same Grafana queries work, but now data comes through Pushgateway:

### **Device Selection Variable**
```
label_values(app_cpu_usage_percent, device_serial)
```

### **Panel Queries**
```bash
# Total CPU by device
total_cpu_usage_percent{device_serial="$device_serial"}

# Top apps CPU usage
app_cpu_usage_percent{device_serial="$device_serial"}

# Total memory by device
total_memory_usage_percent{device_serial="$device_serial"}

# Apps memory usage
app_memory_usage_mb{device_serial="$device_serial"}
```

### **Multi-Device Queries**
```bash
# Compare CPU across all devices
sum by (device_serial) (total_cpu_usage_percent)

# Top CPU app across all devices
topk(1, app_cpu_usage_percent)

# Average memory by device
avg by (device_serial) (total_memory_usage_percent)
```

---

## 🔧 **Advantages of Push Architecture**

### **✅ Benefits**
1. **Firewall Friendly**: Devices initiate connections (no inbound ports)
2. **NAT Compatible**: Works behind NAT/routers
3. **Intermittent Connectivity**: Handles temporary disconnections
4. **Scalable**: Easy to add new devices
5. **Remote Monitoring**: Devices can be anywhere with internet
6. **Configurable Push Frequency**: Adjust based on requirements

### **📊 Current Status**
- **Device**: `GWHV4X1Y4L` (your Mac)
- **Total CPU**: 25.2%  
- **Push Interval**: 2 seconds
- **Status**: ✅ **ACTIVE & PUSHING**

---

## 🔍 **Monitoring & Troubleshooting**

### **Check Push Status**
```bash
# View pushgateway metrics
curl http://localhost:9091/metrics | grep device_serial

# Check last push time
curl http://localhost:9091/metrics | grep push_time_seconds

# View device metrics
curl "http://localhost:9090/api/v1/query?query=total_cpu_usage_percent"
```

### **Debug Push Issues**
```bash
# Test pushgateway connectivity
curl http://localhost:9091/metrics

# Run monitor with verbose logging
python3 push_monitor.py --interval 1 --pushgateway http://localhost:9091

# Check container logs
docker-compose logs pushgateway
docker-compose logs prometheus
```

### **Verify Data Flow**
1. **Device** → Check push_monitor.py logs
2. **Pushgateway** → http://localhost:9091/metrics
3. **Prometheus** → http://localhost:9090/targets  
4. **Grafana** → Dashboard shows real-time data

---

## 🎛️ **Production Deployment**

### **Systemd Service (Linux)**
```bash
# Create service file: /etc/systemd/system/push-monitor.service
[Unit]
Description=Push Monitor Service
After=network.target

[Service]
Type=simple
User=monitoring
WorkingDirectory=/opt/monitoring
ExecStart=/usr/bin/python3 push_monitor.py --pushgateway http://pushgateway:9091
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

# Enable and start
sudo systemctl enable push-monitor
sudo systemctl start push-monitor
```

### **Docker Deployment**
```dockerfile
FROM python:3.11-slim
COPY requirements.txt push_monitor.py /app/
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["python3", "push_monitor.py", "--pushgateway", "http://pushgateway:9091"]
```

---

## 🚀 **Your System is Ready!**

✅ **Push-based architecture successfully implemented**
✅ **Device `GWHV4X1Y4L` actively pushing metrics**  
✅ **Grafana dashboards compatible with pushed data**
✅ **Scalable for multiple devices**

**Next Steps:**
1. Open Grafana: http://localhost:3000
2. Import your dashboard configuration
3. Select device serial from dropdown
4. Deploy `push_monitor.py` on additional devices

The system now supports distributed monitoring with devices pushing metrics from anywhere! 🌍
