#!/usr/local/bin/bash

for SERVICE in neutron nova
do

    mkdir -p /var/lib/$SERVICE
    pw useradd -n $SERVICE -s /bin/false/ -m /var/lib/$SERVICE
    if [ "$SERVICE" == 'nova' ]; then
        pw usermod -G libvirtd $SERVICE
    fi

    mkdir -p /var/log/$SERVICE
    mkdir -p /etc/$SERVICE

    chown -R $SERVICE:$SERVICE /var/log/$SERVICE
    chown -R $SERVICE:$SERVICE /var/lib/$SERVICE
    chown -R $SERVICE:$SERVICE /etc/$SERVICE

    if [ "$SERVICE" == 'neutron' ]; then
        mkdir -p /etc/$SERVICE/rootwrap.d
    fi

done
