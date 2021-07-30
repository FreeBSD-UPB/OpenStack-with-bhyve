#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


from oslo_policy import policy

from nova.policies import base


RULE_AOO = base.RULE_ADMIN_OR_OWNER
SERVERS = 'os_compute_api:servers:%s'
NETWORK_ATTACH_EXTERNAL = 'network:attach_external_network'
ZERO_DISK_FLAVOR = SERVERS % 'create:zero_disk_flavor'
REQUESTED_DESTINATION = 'compute:servers:create:requested_destination'

rules = [
    policy.DocumentedRuleDefault(
        SERVERS % 'index',
        RULE_AOO,
        "List all servers",
        [
            {
                'method': 'GET',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'detail',
        RULE_AOO,
        "List all servers with detailed information",
        [
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'index:get_all_tenants',
        base.RULE_ADMIN_API,
        "List all servers for all projects",
        [
            {
                'method': 'GET',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'detail:get_all_tenants',
        base.RULE_ADMIN_API,
        "List all servers with detailed information for all projects",
        [
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'allow_all_filters',
        base.RULE_ADMIN_API,
        "Allow all filters when listing servers",
        [
            {
                'method': 'GET',
                'path': '/servers'
            },
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'show',
        RULE_AOO,
        "Show a server",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
            }
        ]),
    # the details in host_status are pretty sensitive, only admins
    # should do that by default.
    policy.DocumentedRuleDefault(
        SERVERS % 'show:host_status',
        base.RULE_ADMIN_API,
        "Show a server with additional host status information",
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
            },
            {
                'method': 'GET',
                'path': '/servers/detail'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'create',
        RULE_AOO,
        "Create a server",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'create:forced_host',
        base.RULE_ADMIN_API,
        """
Create a server on the specified host and/or node.

In this case, the server is forced to launch on the specified
host and/or node by bypassing the scheduler filters unlike the
``compute:servers:create:requested_destination`` rule.
""",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        REQUESTED_DESTINATION,
        base.RULE_ADMIN_API,
        """
Create a server on the requested compute service host and/or
hypervisor_hostname.

In this case, the requested host and/or hypervisor_hostname is
validated by the scheduler filters unlike the
``os_compute_api:servers:create:forced_host`` rule.
""",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'create:attach_volume',
        RULE_AOO,
        "Create a server with the requested volume attached to it",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'create:attach_network',
        RULE_AOO,
        "Create a server with the requested network attached to it",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'create:trusted_certs',
        RULE_AOO,
        "Create a server with trusted image certificate IDs",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        ZERO_DISK_FLAVOR,
        base.RULE_ADMIN_API,
        """
This rule controls the compute API validation behavior of creating a server
with a flavor that has 0 disk, indicating the server should be volume-backed.

For a flavor with disk=0, the root disk will be set to exactly the size of the
image used to deploy the instance. However, in this case the filter_scheduler
cannot select the compute host based on the virtual image size. Therefore, 0
should only be used for volume booted instances or for testing purposes.

WARNING: It is a potential security exposure to enable this policy rule
if users can upload their own images since repeated attempts to
create a disk=0 flavor instance with a large image can exhaust
the local disk of the compute (or shared storage cluster). See bug
https://bugs.launchpad.net/nova/+bug/1739646 for details.
""",
        [
            {
                'method': 'POST',
                'path': '/servers'
            }
        ]),
    policy.DocumentedRuleDefault(
        NETWORK_ATTACH_EXTERNAL,
        'is_admin:True',
        "Attach an unshared external network to a server",
        [
            # Create a server with a requested network or port.
            {
                'method': 'POST',
                'path': '/servers'
            },
            # Attach a network or port to an existing server.
            {
                'method': 'POST',
                'path': '/servers/{server_id}/os-interface'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'delete',
        RULE_AOO,
        "Delete a server",
        [
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'update',
        RULE_AOO,
        "Update a server",
        [
            {
                'method': 'PUT',
                'path': '/servers/{server_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'confirm_resize',
        RULE_AOO,
        "Confirm a server resize",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (confirmResize)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'revert_resize',
        RULE_AOO,
        "Revert a server resize",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (revertResize)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'reboot',
        RULE_AOO,
        "Reboot a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (reboot)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'resize',
        RULE_AOO,
        "Resize a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (resize)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'rebuild',
        RULE_AOO,
        "Rebuild a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (rebuild)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'rebuild:trusted_certs',
        RULE_AOO,
        "Rebuild a server with trusted image certificate IDs",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (rebuild)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'create_image',
        RULE_AOO,
        "Create an image from a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (createImage)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'create_image:allow_volume_backed',
        RULE_AOO,
        "Create an image from a volume backed server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (createImage)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'start',
        RULE_AOO,
        "Start a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-start)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'stop',
        RULE_AOO,
        "Stop a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (os-stop)'
            }
        ]),
    policy.DocumentedRuleDefault(
        SERVERS % 'trigger_crash_dump',
        RULE_AOO,
        "Trigger crash dump in a server",
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/action (trigger_crash_dump)'
            }
        ]),
]


def list_rules():
    return rules
