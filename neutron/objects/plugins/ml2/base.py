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

import abc

import netaddr
import six

from neutron.common import _constants as common_constants
from neutron.objects import base


class EndpointBase(base.NeutronDbObject):

    primary_keys = ['ip_address']

    @classmethod
    def modify_fields_from_db(cls, db_obj):
        result = super(EndpointBase, cls).modify_fields_from_db(db_obj)
        if 'ip_address' in result:
            result['ip_address'] = netaddr.IPAddress(result['ip_address'])
        return result

    @classmethod
    def modify_fields_to_db(cls, fields):
        result = super(EndpointBase, cls).modify_fields_to_db(fields)
        if 'ip_address' in fields:
            result['ip_address'] = cls.filter_to_str(result['ip_address'])
        return result


@six.add_metaclass(abc.ABCMeta)
class SegmentAllocation(object):

    @classmethod
    def get_unallocated_segments(cls, context, **filters):
        with cls.db_context_reader(context):
            columns = set(dict(cls.db_model.__table__.columns))
            model_filters = dict((k, filters[k])
                                 for k in columns & set(filters.keys()))
            query = context.session.query(cls.db_model).filter_by(
                allocated=False, **model_filters)
            return query.limit(common_constants.IDPOOL_SELECT_SIZE).all()

    @classmethod
    def allocate(cls, context, **segment):
        with cls.db_context_writer(context):
            return context.session.query(cls.db_model).filter_by(
                allocated=False, **segment).update({'allocated': True})

    @classmethod
    def deallocate(cls, context, **segment):
        with cls.db_context_writer(context):
            return context.session.query(cls.db_model).filter_by(
                allocated=True, **segment).update({'allocated': False})

    @classmethod
    def update_primary_keys(cls, _dict, segmentation_id=None, **kwargs):
        _dict[cls.primary_keys[0]] = segmentation_id

    @abc.abstractmethod
    def get_segmentation_id(self):
        pass

    @property
    def segmentation_id(self):
        return self.db_obj.segmentation_id
