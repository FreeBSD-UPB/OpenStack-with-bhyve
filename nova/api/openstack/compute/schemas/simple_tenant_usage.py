# Copyright 2017 NEC Corporation.
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
import copy

from nova.api.validation import parameter_types


index_query = {
    'type': 'object',
    'properties': {
        'start': parameter_types.multi_params({'type': 'string'}),
        'end': parameter_types.multi_params({'type': 'string'}),
        'detailed': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

show_query = {
    'type': 'object',
    'properties': {
        'start': parameter_types.multi_params({'type': 'string'}),
        'end': parameter_types.multi_params({'type': 'string'})
    },
    # NOTE(gmann): This is kept True to keep backward compatibility.
    # As of now Schema validation stripped out the additional parameters and
    # does not raise 400. In microversion 2.75, we have blocked the additional
    # parameters.
    'additionalProperties': True
}

index_query_v240 = copy.deepcopy(index_query)
index_query_v240['properties'].update(
    parameter_types.pagination_parameters)

show_query_v240 = copy.deepcopy(show_query)
show_query_v240['properties'].update(
    parameter_types.pagination_parameters)

index_query_275 = copy.deepcopy(index_query_v240)
index_query_275['additionalProperties'] = False

show_query_275 = copy.deepcopy(show_query_v240)
show_query_275['additionalProperties'] = False
