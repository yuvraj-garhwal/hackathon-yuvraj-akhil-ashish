#!/bin/bash

# CPU Monitor PoC Setup Script
echo "🚀 Setting up CPU Monitor PoC..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Install Python dependencies
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# Start Docker containers
echo "🐳 Starting Prometheus and Grafana containers..."
docker-compose up -d

# Wait for services to be ready
echo "⏳ Waiting for services to start (30 seconds)..."
sleep 30

# Check if services are running
echo "🔍 Checking service status..."
if docker-compose ps | grep -q "Up"; then
    echo "✅ Services are running!"
    echo ""
    echo "🎯 Access URLs:"
    echo "   Grafana:     http://localhost:3000 (admin/admin)"
    echo "   Prometheus:  http://localhost:9090"
    echo "   Metrics:     http://localhost:8000/metrics"
    echo ""
    echo "🔧 To start monitoring, run:"
    echo "   python cpu_monitor.py"
    echo ""
    echo "📊 The dashboard will auto-refresh every second with real-time data!"
else
    echo "❌ Some services failed to start. Check with 'docker-compose logs'"
fi
