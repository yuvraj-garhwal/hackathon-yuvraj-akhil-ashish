#!/usr/bin/env python3
"""
Test script to verify the CPU monitor functionality
"""

import time
import requests
import subprocess
import threading
from cpu_monitor import CPUMonitor

def test_metrics_endpoint():
    """Test if metrics endpoint is working"""
    try:
        response = requests.get('http://localhost:8000/metrics', timeout=5)
        if response.status_code == 200:
            print("✅ Metrics endpoint is working")
            print(f"📊 Response contains {len(response.text.split('\\n'))} lines of metrics")
            return True
        else:
            print(f"❌ Metrics endpoint returned status {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to connect to metrics endpoint: {e}")
        return False

def test_monitor_functionality():
    """Test basic monitor functionality"""
    try:
        monitor = CPUMonitor(top_n=5)
        top_processes = monitor.get_top_cpu_processes()
        
        if len(top_processes) > 0:
            print(f"✅ Monitor found {len(top_processes)} processes")
            print("📈 Top processes:")
            for i, proc in enumerate(top_processes[:3], 1):
                print(f"   {i}. {proc['name']} - {proc['cpu_percent']:.1f}% CPU")
            return True
        else:
            print("❌ Monitor found no processes")
            return False
    except Exception as e:
        print(f"❌ Monitor test failed: {e}")
        return False

def run_monitor_briefly():
    """Run monitor for a few seconds to test metrics generation"""
    def monitor_thread():
        monitor = CPUMonitor(top_n=10)
        try:
            monitor.start_monitoring(port=8000, interval=1)
        except KeyboardInterrupt:
            pass
    
    thread = threading.Thread(target=monitor_thread, daemon=True)
    thread.start()
    
    # Wait for monitor to start
    time.sleep(3)
    return thread

def main():
    print("🧪 Testing CPU Monitor functionality...")
    print("=" * 50)
    
    # Test 1: Basic functionality
    print("🔍 Test 1: Basic monitor functionality")
    test1_result = test_monitor_functionality()
    print()
    
    # Test 2: Start monitor and test endpoint
    print("🔍 Test 2: Starting monitor and testing metrics endpoint")
    monitor_thread = run_monitor_briefly()
    
    # Wait a bit for metrics to be generated
    time.sleep(2)
    
    test2_result = test_metrics_endpoint()
    print()
    
    # Summary
    print("=" * 50)
    print("📋 Test Summary:")
    print(f"   Basic functionality: {'✅ PASS' if test1_result else '❌ FAIL'}")
    print(f"   Metrics endpoint:    {'✅ PASS' if test2_result else '❌ FAIL'}")
    
    if test1_result and test2_result:
        print("🎉 All tests passed! The monitor is working correctly.")
        print()
        print("🚀 To start the full system:")
        print("   1. Run: ./setup.sh")
        print("   2. Run: python cpu_monitor.py")
        print("   3. Open: http://localhost:3000")
    else:
        print("💥 Some tests failed. Check the error messages above.")
    
    print("\n⏹️  Test completed.")

if __name__ == "__main__":
    main()
