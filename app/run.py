#!/usr/bin/env python3

import sys
import os
import requests
import asyncio
import aiohttp
import json
import logging
import urllib3
from configparser import ConfigParser


class Proxmox:
    def __init__(self, proxmox_url, proxmox_node_name, proxmox_token_name, proxmox_token, ip_net_prefix):
        self.proxmox_url = proxmox_url
        self.proxmox_node_name = proxmox_node_name
        self.proxmox_token = f"PVEAPIToken={proxmox_token_name}={proxmox_token}"
        self.ip_net_prefix = ip_net_prefix

    async def get_vms(self):
        """get vms from proxmox server"""
        try:
            async with aiohttp.ClientSession() as session:
                # get all vms from proxmox
                async with session.get(f"{self.proxmox_url}/api2/json/nodes/{proxmox_node_name}/qemu", headers={"Authorization": self.proxmox_token}, verify_ssl=False) as r:
                    r.raise_for_status()
                    vms = json.loads(await r.text())
                    vms = self._filter_vms(vms['data'])

                # get ip address for each vm
                tasks = [ asyncio.create_task(self.get_vm_ip(session, vm)) for vm in vms ]
                return await asyncio.gather(*tasks)

        except Exception as err:
            logging.exception('Error while getting VM list from Proxmox')
            return False

    async def get_vm_ip(self, session, vm):
        """get vms from proxmox server"""
        try:
            vmid = vm['vmid']

            # get nic info for vm
            nic_info = await self.get_vm_nics(session, vmid)

            # get ip address from nic info
            ip_address = self.get_ip_from_nics(nic_info)

            # did we find the ip address, or should we predict it?
            if ip_address:
                vm['ip_address'] = ip_address
                logging.info(f"IP address for {vmid} is {vm['ip_address']}")
            else:
                vm['ip_address'] = f"{self.ip_net_prefix}.{vmid}"
                logging.info(f"Unable to lookup IP address for {vmid}. Using predicted address of {vm['ip_address']}")

            return vm

        except Exception as err:
            logging.exception(f'Error while getting IP address for {vmid}')
            return False

    async def get_vm_nics(self, session, vmid):
        try:
            async with session.get(f"{self.proxmox_url}/api2/json/nodes/{proxmox_node_name}/qemu/{vmid}/agent/network-get-interfaces", headers={"Authorization": self.proxmox_token}, verify_ssl=False) as r:
                r.raise_for_status()
                return json.loads(await r.text())['data']['result']
        except Exception as ex:
            return False

        if 'error' in results:
            return False

    def get_ip_from_nics(self, nic_info):
        # look for ip address beginning with ip_net_prefix
        if nic_info:
            for interface in nic_info:
                for ip_address_type in interface["ip-addresses"]:
                    if ip_net_prefix in ip_address_type['ip-address']:
                        return ip_address_type['ip-address']
        return False


    def _filter_vms(self, vms):
        """remove templates and other unneeded info from vm list"""
        # remove templates from list so we only have vms
        no_templates = [d for d in vms if d['template'] != 1]

        # remove everything except name and vmid from each dict in list
        filtered = [{k:v for k,v in d.items() if k in ('name', 'vmid')} for d in no_templates]
        return filtered


class Cloudflare:
    def __init__(self, cloudflare_token, cloudflare_zone_name):
        self.cloudflare_token = cloudflare_token
        self.cloudflare_zone_name = cloudflare_zone_name

    async def update_record(self, record_name, ip_address):
        async with aiohttp.ClientSession() as session:
            if not getattr(self, 'zone_id', None):
                self.zone_id = await self._lookup_zone_id(session)

            if not self.zone_id:
                raise Exception("Failed to look up zone id")

            record_id = await self._lookup_record_id(session, record_name)
            if record_id:
                if await self._update_record(session, record_name, record_id, ip_address):
                    logging.info(f"Updated record for {record_name} ({ip_address})")
                else:
                    raise Exception("Failed to update record")
            else:
                if await self._create_record(session, record_name, ip_address):
                    logging.info(f"Created record for {record_name} ({ip_address})")
                else:
                    raise Exception("Failed to create record")

    async def _lookup_zone_id(self, session):
        """lookup zone id given zone name"""
        try:
            async with session.get(f"https://api.cloudflare.com/client/v4/zones?name={self.cloudflare_zone_name}", headers={"Authorization": f"Bearer {self.cloudflare_token}"}) as r:
                r.raise_for_status()
                zone_id = json.loads(await r.text())['result'][0]['id']
                logging.debug(f"Zone ID lookup finished: {zone_id}")
                return zone_id
        except Exception:
            logging.exception("Failed to look up zone id")

    async def _lookup_record_id(self, session, record_name):
        """lookup A record and return record ID if exists or False if it doesnt"""
        try:
            async with session.get(f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/dns_records?name={record_name}", headers={"Authorization": f"Bearer {self.cloudflare_token}"}) as r:
                r.raise_for_status()
                response = json.loads(await r.text())
                if len(response['result']) == 0:
                    logging.debug(f"Record for {record_name} not found")
                    return False
                record_id = response['result'][0]['id']
                logging.debug(f"Record {record_name} has record ID {record_id}")
                return record_id
        except Exception:
            logging.exception(f"Failed to look up record id for {record_name} or it does not exist")

    async def _create_record(self, session, record_name, ip_address):
        """create A record and return record id"""
        try:
            payload = {"type": "A", "name": record_name, "content": ip_address, "ttl": 120, "priority": 10, "proxied": False}
            async with session.post(f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/dns_records", headers={"Authorization": f"Bearer {self.cloudflare_token}"}, json=payload) as r:
                r.raise_for_status()
                record_id = json.loads(await r.text())['result']['id']
                logging.debug(f"Record {record_name} created with {ip_address} record ID {record_id}")
                return record_id
        except Exception:
            logging.exception(f"Failed to create record for {record_name} ({ip_address})")

    async def _update_record(self, session, record_name, record_id, ip_address):
        """update A record and return record id"""
        try:
            payload = {"type": "A", "name": record_name, "content": ip_address, "ttl": 120, "priority": 10, "proxied": False}
            async with session.put(f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/dns_records/{record_id}", headers={"Authorization": f"Bearer {self.cloudflare_token}"}, json=payload) as r:
                r.raise_for_status()
                record_id = json.loads(await r.text())['result']['id']
                logging.debug(f"Record {record_name} updated to {ip_address} record ID {record_id}")
                return record_id
        except Exception:
            logging.exception(f"Failed to update record for {record_name} ({ip_address})")

async def sync_to_cloudflare(cloudflare_token, cloudflare_zone, cloudflare_dns_subdomain, vms):
    cf = Cloudflare(cloudflare_token, cloudflare_zone)
    tasks = []
    for vm in vms:
        if cloudflare_dns_subdomain:
            tasks.append(asyncio.create_task(cf.update_record(f"{vm['name']}.{cloudflare_dns_subdomain}.{cloudflare_zone}", vm['ip_address'])))
        else:
            tasks.append(asyncio.create_task(cf.update_record(f"{vm['name']}.{cloudflare_zone}", vm['ip_address'])))
    await asyncio.gather(*tasks)

async def pull_from_proxmox(proxmox_url, proxmox_node_name, proxmox_token_name, proxmox_token, ip_net_prefix):
    proxmox = Proxmox(proxmox_url, proxmox_node_name, proxmox_token_name, proxmox_token, ip_net_prefix)
    return await proxmox.get_vms()


# hide SSL/TLS warnings
urllib3.disable_warnings()

# set up logging
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

# load settings
try:
    config = ConfigParser()
    config.read(os.path.join(os.path.dirname(__file__), 'config.ini'))
    ip_net_prefix = config.get('main', 'ip_net_prefix')
    proxmox_url = config.get('proxmox', 'proxmox_url')
    proxmox_token_name = config.get('proxmox', 'proxmox_token_name')
    proxmox_token = config.get('proxmox', 'proxmox_token')
    proxmox_node_name = config.get('proxmox', 'proxmox_node_name')
    cloudflare_token = config.get('cloudflare', 'cloudflare_token')
    cloudflare_zone = config.get('cloudflare', 'cloudflare_zone')
    cloudflare_dns_subdomain = config.get('cloudflare', 'cloudflare_dns_subdomain', fallback=None)
except FileNotFoundError as err:
    logging.exception(f"Unable to read config file! Error: {err}")
    exit()
except Exception as err:
    logging.exception("Unable to parse config.ini or missing settings! Error: {err}")
    exit()

vms = asyncio.run(pull_from_proxmox(proxmox_url, proxmox_node_name, proxmox_token_name, proxmox_token, ip_net_prefix))
if vms:
    asyncio.run(sync_to_cloudflare(cloudflare_token, cloudflare_zone, cloudflare_dns_subdomain, vms))
else:
    logging.critical("Unable to get VM list from Proxmox")
