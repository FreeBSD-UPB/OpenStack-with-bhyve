# Copyright 2017 Huawei Technologies Co.,LTD.
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


from oslo_log import log as logging
from sqlalchemy import MetaData, Table, Index

LOG = logging.getLogger(__name__)


def _get_table_index(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    table = Table('compute_nodes', meta, autoload=True)
    for idx in table.indexes:
        if idx.columns.keys() == ['uuid']:
            break
    else:
        idx = None
    return table, idx


def upgrade(migrate_engine):
    table, index = _get_table_index(migrate_engine)
    if index:
        LOG.info('Skipped adding compute_nodes_uuid_idx because an '
                 'equivalent index already exists.')
        return
    index = Index('compute_nodes_uuid_idx', table.c.uuid, unique=True)
    index.create(migrate_engine)
