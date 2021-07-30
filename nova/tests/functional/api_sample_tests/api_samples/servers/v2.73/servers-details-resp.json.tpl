{
    "servers": [
        {
            "OS-DCF:diskConfig": "AUTO",
            "OS-EXT-AZ:availability_zone": "nova",
            "OS-EXT-SRV-ATTR:host": "compute",
            "OS-EXT-SRV-ATTR:hostname": "new-server-test",
            "OS-EXT-SRV-ATTR:hypervisor_hostname": "fake-mini",
            "OS-EXT-SRV-ATTR:instance_name": "instance-00000001",
            "OS-EXT-SRV-ATTR:kernel_id": "",
            "OS-EXT-SRV-ATTR:launch_index": 0,
            "OS-EXT-SRV-ATTR:ramdisk_id": "",
            "OS-EXT-SRV-ATTR:reservation_id": "%(reservation_id)s",
            "OS-EXT-SRV-ATTR:root_device_name": "/dev/sda",
            "OS-EXT-SRV-ATTR:user_data": "IyEvYmluL2Jhc2gKL2Jpbi9zdQplY2hvICJJIGFtIGluIHlvdSEiCg==",
            "OS-EXT-STS:power_state": 1,
            "OS-EXT-STS:task_state": null,
            "OS-EXT-STS:vm_state": "active",
            "OS-SRV-USG:launched_at": "%(strtime)s",
            "OS-SRV-USG:terminated_at": null,
            "accessIPv4": "1.2.3.4",
            "accessIPv6": "80fe::",
            "addresses": {
                "private": [
                    {
                        "OS-EXT-IPS-MAC:mac_addr": "aa:bb:cc:dd:ee:ff",
                        "OS-EXT-IPS:type": "fixed",
                        "addr": "%(ip)s",
                        "version": 4
                    }
                ]
            },
            "config_drive": "",
            "created": "%(isotime)s",
            "description": null,
            "flavor": {
                "disk": 1,
                "ephemeral": 0,
                "extra_specs": {},
                "original_name": "m1.tiny",
                "ram": 512,
                "swap": 0,
                "vcpus": 1
            },
            "hostId": "2091634baaccdc4c5a1d57069c833e402921df696b7f970791b12ec6",
            "host_status": "UP",
            "id": "%(id)s",
            "image": {
                "id": "%(uuid)s",
                "links": [
                    {
                        "href": "%(compute_endpoint)s/images/%(uuid)s",
                        "rel": "bookmark"
                    }
                ]
            },
            "key_name": null,
            "links": [
                {
                    "href": "%(versioned_compute_endpoint)s/servers/%(uuid)s",
                    "rel": "self"
                },
                {
                    "href": "%(compute_endpoint)s/servers/%(id)s",
                    "rel": "bookmark"
                }
            ],
            "locked": true,
            "locked_reason": "I don't want to work",
            "metadata": {
                "My Server Name": "Apache1"
            },
            "name": "new-server-test",
            "os-extended-volumes:volumes_attached": [],
            "progress": 0,
            "security_groups": [
                {
                    "name": "default"
                }
            ],
            "status": "ACTIVE",
            "tags": [],
            "tenant_id": "6f70656e737461636b20342065766572",
            "trusted_image_certificates": null,
            "updated": "%(isotime)s",
            "user_id": "fake"
        }
    ]
}