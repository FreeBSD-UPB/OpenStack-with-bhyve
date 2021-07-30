# Copyright 2014 NEC Corporation.  All rights reserved.
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

from nova.api.validation import parameter_types

update = {
    'type': 'object',
    'properties': {
        'status': {
             'type': 'string',
             'enum': ['enable', 'disable',
                      'Enable', 'Disable',
                      'ENABLE', 'DISABLE'],
        },
        'maintenance_mode': {
             'type': 'string',
             'enum': ['enable', 'disable',
                      'Enable', 'Disable',
                      'ENABLE', 'DISABLE'],
        },
        'anyOf': [
            {'required': ['status']},
            {'required': ['maintenance_mode']}
        ],
    },
    'additionalProperties': False
}

index_query = {
    'type': 'object',
    'properties': {
        'zone': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. This API is deprecated in microversion 2.43 so we
    # do not to update the additionalProperties to False.
    'additionalProperties': True
}
