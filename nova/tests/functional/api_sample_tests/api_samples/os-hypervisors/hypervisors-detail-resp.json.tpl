{
    "hypervisors": [
        {
            "cpu_info": "{\"arch\": \"x86_64\", \"model\": \"Nehalem\", \"vendor\": \"Intel\", \"features\": [\"pge\", \"clflush\"], \"topology\": {\"cores\": 1, \"threads\": 1, \"sockets\": 4}}",
            "current_workload": 0,
            "state": "up",
            "status": "enabled",
            "disk_available_least": 0,
            "host_ip": "%(ip)s",
            "free_disk_gb": 1028,
            "free_ram_mb": 7680,
            "hypervisor_hostname": "fake-mini",
            "hypervisor_type": "fake",
            "hypervisor_version": 1000,
            "id": %(hypervisor_id)s,
            "local_gb": 1028,
            "local_gb_used": 0,
            "memory_mb": 8192,
            "memory_mb_used": 512,
            "running_vms": 0,
            "service": {
                "host": "%(host_name)s",
                "id": "%(int:service_id)s",
                "disabled_reason": null
            },
            "vcpus": 2,
            "vcpus_used": 0
        }
    ]
}
