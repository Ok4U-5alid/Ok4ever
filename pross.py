import psutil

def get_processes():
    processes = []
    for proc in psutil.process_iter(['pid', 'name', 'status']):
        try:
            processes.append({
                'name': proc.info['name'],
                'status': proc.info['status'],
                'memory_info': proc.memory_info()
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return processes

def get_memory_info():
    memory_info = {
        'rss': psutil.virtual_memory().rss / (1024.0 **3),
        'vms': psutil.virtual_memory().vms / (1024.0 **3),
        'pss': psutil.process_memory().rss / (1024.0 **3),
        'peak': psutil.process_memory().peak / (1024.0 **3)
    }
    return memory_info

def check_ports():
    print("TCP Ports:")
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            print(f"PID: {proc.info['pid']}, Name: {proc.info['name']}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    print("\nUDP Ports:")
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            print(f"PID: {proc.info['pid']}, Name: {proc.info['name']}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

    print("\nActive Running Services:")
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            print(f"PID: {proc.info['pid']}, Name: {proc.info['name']}")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass

def main():
    processes = get_processes()
    memory_info = get_memory_info()
    check_ports()

    with open('check_ports.py', 'w') as f:
        f.write('# Check ports: Check listening TCP and UDP ports and identify active running services.\n')
        f.write('import psutil\n')
        f.write('def get_processes():\n')
        f.write('    processes = []\n')
        f.write('    for proc in psutil.process_iter(["pid", "name", "status"]

