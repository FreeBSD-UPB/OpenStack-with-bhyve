# Copyright (c) 2012 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


policy_data = """
{
    "context_is_admin": "role:admin or role:administrator",

    "os_compute_api:servers:show:host_status": "",
    "os_compute_api:servers:allow_all_filters": "",
    "os_compute_api:servers:migrations:force_complete": "",
    "os_compute_api:os-admin-actions:inject_network_info": "",
    "os_compute_api:os-admin-actions:reset_network": "",
    "os_compute_api:os-admin-actions:reset_state": "",
    "os_compute_api:os-admin-password": "",
    "os_compute_api:os-agents": "",
    "os_compute_api:os-attach-interfaces": "",
    "os_compute_api:os-baremetal-nodes": "",
    "os_compute_api:os-console-output": "",
    "os_compute_api:os-remote-consoles": "",
    "os_compute_api:os-consoles:create": "",
    "os_compute_api:os-consoles:delete": "",
    "os_compute_api:os-consoles:index": "",
    "os_compute_api:os-consoles:show": "",
    "os_compute_api:os-create-backup": "",
    "os_compute_api:os-deferred-delete": "",
    "os_compute_api:os-extended-server-attributes": "",
    "os_compute_api:ips:index": "",
    "os_compute_api:ips:show": "",
    "os_compute_api:extensions": "",
    "os_compute_api:os-flavor-access:remove_tenant_access": "",
    "os_compute_api:os-flavor-access:add_tenant_access": "",
    "os_compute_api:os-flavor-extra-specs:index": "",
    "os_compute_api:os-flavor-extra-specs:show": "",
    "os_compute_api:os-flavor-manage:create": "",
    "os_compute_api:os-flavor-manage:update": "",
    "os_compute_api:os-flavor-manage:delete": "",
    "os_compute_api:os-floating-ip-pools": "",
    "os_compute_api:os-floating-ips": "",
    "os_compute_api:os-instance-actions": "",
    "os_compute_api:os-instance-usage-audit-log": "",

    "os_compute_api:os-lock-server:lock": "",
    "os_compute_api:os-lock-server:unlock": "",
    "os_compute_api:os-migrate-server:migrate": "",
    "os_compute_api:os-migrate-server:migrate_live": "",
    "os_compute_api:os-multinic": "",
    "os_compute_api:os-networks": "",
    "os_compute_api:os-networks:view": "",
    "os_compute_api:os-networks-associate": "",
    "os_compute_api:os-tenant-networks": "",
    "os_compute_api:os-pause-server:pause": "",
    "os_compute_api:os-pause-server:unpause": "",
    "os_compute_api:os-quota-sets:show": "",
    "os_compute_api:os-quota-sets:update": "",
    "os_compute_api:os-quota-sets:delete": "",
    "os_compute_api:os-quota-sets:detail": "",
    "os_compute_api:os-quota-sets:defaults": "",
    "os_compute_api:os-quota-class-sets:update": "",
    "os_compute_api:os-quota-class-sets:show": "",
    "os_compute_api:os-rescue": "",
    "os_compute_api:os-security-group-default-rules": "",
    "os_compute_api:os-server-diagnostics": "",
    "os_compute_api:os-server-password": "",
    "os_compute_api:os-server-tags:index": "",
    "os_compute_api:os-server-tags:show": "",
    "os_compute_api:os-server-tags:update": "",
    "os_compute_api:os-server-tags:update_all": "",
    "os_compute_api:os-server-tags:delete": "",
    "os_compute_api:os-server-tags:delete_all": "",
    "os_compute_api:os-server-groups:show": "",
    "os_compute_api:os-server-groups:index": "",
    "os_compute_api:os-server-groups:create": "",
    "os_compute_api:os-server-groups:delete": "",
    "os_compute_api:os-services": "",
    "os_compute_api:os-shelve:shelve": "",
    "os_compute_api:os-shelve:shelve_offload": "",
    "os_compute_api:os-simple-tenant-usage:show": "",
    "os_compute_api:os-simple-tenant-usage:list": "",
    "os_compute_api:os-shelve:unshelve": "",
    "os_compute_api:os-suspend-server:suspend": "",
    "os_compute_api:os-suspend-server:resume": "",
    "os_compute_api:os-volumes": "",
    "os_compute_api:os-volumes-attachments:index": "",
    "os_compute_api:os-volumes-attachments:show": "",
    "os_compute_api:os-volumes-attachments:create": "",
    "os_compute_api:os-volumes-attachments:update": "",
    "os_compute_api:os-volumes-attachments:delete": "",
    "os_compute_api:os-availability-zone:list": "",
    "os_compute_api:os-availability-zone:detail": "",
    "os_compute_api:limits": "",
    "os_compute_api:os-assisted-volume-snapshots:create": "",
    "os_compute_api:os-assisted-volume-snapshots:delete": "",
    "os_compute_api:server-metadata:create": "",
    "os_compute_api:server-metadata:update": "",
    "os_compute_api:server-metadata:update_all": "",
    "os_compute_api:server-metadata:delete": "",
    "os_compute_api:server-metadata:show": "",
    "os_compute_api:server-metadata:index": ""
}
"""
