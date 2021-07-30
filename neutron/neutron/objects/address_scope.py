# Copyright (c) 2016 Intel Corporation.
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

from oslo_versionedobjects import fields as obj_fields

from neutron.db.models import address_scope as models
from neutron.db import models_v2
from neutron.objects import base
from neutron.objects import common_types


@base.NeutronObjectRegistry.register
class AddressScope(base.NeutronDbObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    db_model = models.AddressScope

    fields = {
        'id': common_types.UUIDField(),
        'project_id': obj_fields.StringField(nullable=True),
        'name': obj_fields.StringField(),
        'shared': obj_fields.BooleanField(),
        'ip_version': common_types.IPVersionEnumField(),
    }

    @classmethod
    def get_network_address_scope(cls, context, network_id, ip_version):
        query = context.session.query(cls.db_model)
        query = query.join(
            models_v2.SubnetPool,
            models_v2.SubnetPool.address_scope_id == cls.db_model.id)
        query = query.filter(
            cls.db_model.ip_version == ip_version,
            models_v2.Subnet.subnetpool_id == models_v2.SubnetPool.id,
            models_v2.Subnet.network_id == network_id)
        scope_model_obj = query.one_or_none()

        if scope_model_obj:
            return cls._load_object(context, scope_model_obj)

        return None
