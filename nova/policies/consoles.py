# Copyright 2016 Cloudbase Solutions Srl
# All Rights Reserved.
#
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


POLICY_ROOT = 'os_compute_api:os-consoles:%s'


consoles_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'create',
        base.RULE_ADMIN_OR_OWNER,
        'Create a console for a server instance',
        [
            {
                'method': 'POST',
                'path': '/servers/{server_id}/consoles'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'show',
        base.RULE_ADMIN_OR_OWNER,
        'Show console details for a server instance',
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}/consoles/{console_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'delete',
        base.RULE_ADMIN_OR_OWNER,
        'Delete a console for a server instance',
        [
            {
                'method': 'DELETE',
                'path': '/servers/{server_id}/consoles/{console_id}'
            }
        ]),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'index',
        base.RULE_ADMIN_OR_OWNER,
        'List all consoles for a server instance',
        [
            {
                'method': 'GET',
                'path': '/servers/{server_id}/consoles'
            }
        ])
]


def list_rules():
    return consoles_policies
