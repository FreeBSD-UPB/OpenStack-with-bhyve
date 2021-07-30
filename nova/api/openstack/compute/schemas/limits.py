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

import copy

from nova.api.validation import parameter_types


limits_query_schema = {
    'type': 'object',
    'properties': {
        'tenant_id': parameter_types.common_query_param,
    },
    # For backward compatible changes
    # In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

limits_query_schema_275 = copy.deepcopy(limits_query_schema)
limits_query_schema_275['additionalProperties'] = False
