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


POLICY_ROOT = 'os_compute_api:os-lock-server:%s'


lock_server_policies = [
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'lock',
        base.RULE_ADMIN_OR_OWNER,
        "Lock a server",
        [
            {
                'path': '/servers/{server_id}/action (lock)',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'unlock',
        base.RULE_ADMIN_OR_OWNER,
        "Unlock a server",
        [
            {
                'path': '/servers/{server_id}/action (unlock)',
                'method': 'POST'
            }
        ]
    ),
    policy.DocumentedRuleDefault(
        POLICY_ROOT % 'unlock:unlock_override',
        base.RULE_ADMIN_API,
        """Unlock a server, regardless who locked the server.

This check is performed only after the check
os_compute_api:os-lock-server:unlock passes""",
        [
            {
                'path': '/servers/{server_id}/action (unlock)',
                'method': 'POST'
            }
        ]
    ),
]


def list_rules():
    return lock_server_policies
