import psutil
import os

# Check CPU usage
print("CPU usage: ", psutil.cpu_percent())

# Check memory usage
print("Memory usage: ", psutil.virtual_memory().percent)

# Check disk usage
print("Disk usage: ", psutil.disk_usage("/").percent)

# Check system uptime
print("System uptime: ", psutil.boot_time())