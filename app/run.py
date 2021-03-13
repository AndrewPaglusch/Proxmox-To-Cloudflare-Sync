#!/usr/bin/env python3

import sys
import os
import asyncio
import aiohttp
import json
import logging
import urllib3
from configparser import ConfigParser


class Proxmox:
    def __init__(self, proxmox_url, proxmox_nodes, proxmox_token_name, proxmox_token, ip_net_prefix):
        self.proxmox_url = proxmox_url
        self.proxmox_nodes = proxmox_nodes
        self.proxmox_token = f"PVEAPIToken={proxmox_token_name}={proxmox_token}"
        self.ip_net_prefix = ip_net_prefix

    async def get_vms(self):
        """get vms from proxmox server"""
        try:
            async with aiohttp.ClientSession() as session:
                # get all vms from proxmox
                tasks = []
                for node in self.proxmox_nodes:
                    logging.debug(f"Retrieving VMs from node {node}...")
                    async with session.get(f"{self.proxmox_url}/api2/json/nodes/{node}/qemu", headers={"Authorization": self.proxmox_token}, verify_ssl=False) as r:
                        r.raise_for_status()
                        response = json.loads(await r.text())
                        vms = self._filter_vms(response['data'])
                        tasks.extend([ asyncio.create_task(self.get_vm_ip(session, node, vm)) for vm in vms ])
                        logging.debug(f"Found {len(vms)} VMs on node {node}")

                # get ip address for each vm
                vms = await asyncio.gather(*tasks)

                # remove None items from list
                vms = [ i for i in vms if i is not None ]
                return vms

        except Exception:
            logging.exception('Error while getting VM list from Proxmox')
            return False

    async def get_vm_ip(self, session, node, vm):
        """get vms from proxmox server"""
        try:
            vmid = vm['vmid']

            # get nic info for vm
            nic_info = await self.get_vm_nics(session, node, vmid)
            ip_address = None
            if nic_info:
                # get ip address from nic info
                ip_address = self.get_ip_from_nics(nic_info)

            # did we find the ip address, or should we predict it?
            if ip_address:
                vm['ip_address'] = ip_address
                logging.info(f"IP address for {vmid} on {node} is {vm['ip_address']}")
            else:
                if int(vmid) > 254:
                    logging.info(f"Unable to lookup IP address for {vmid} on {node}. Not generating a predicted address because the ID ({vmid}) is greater than 254")
                    return
                else:
                    vm['ip_address'] = f"{self.ip_net_prefix}.{vmid}"
                    logging.info(f"Unable to lookup IP address for {vmid} on {node}. Using predicted address of {vm['ip_address']}")

            return vm

        except Exception:
            logging.exception(f'Error while getting IP address for {vmid}')
            return False

    async def get_vm_nics(self, session, node, vmid):
        try:
            async with session.get(f"{self.proxmox_url}/api2/json/nodes/{node}/qemu/{vmid}/agent/network-get-interfaces", headers={"Authorization": self.proxmox_token}, verify_ssl=False) as r:
                r.raise_for_status()
                results = json.loads(await r.text())['data']['result']

                if 'error' in results:
                    return False

                return results

        except Exception:
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

    async def setup(self):
        """get zone_id and records for zone. must be called before you can call update_record"""
        async with aiohttp.ClientSession() as session:
            self.zone_id = await self._lookup_zone_id(session)
            if not self.zone_id:
                return False

            self.zone_records = await self._get_records(session)
            if not self.zone_records:
                return False

            return True

    async def update_record(self, record_name, ip_address):
        """update record with given ip address"""
        # see if the record is already in zone how we want it
        if record_name in self.zone_records.keys():
            if self.zone_records[record_name]['ip_address'] == ip_address:
                logging.info(f"Skipping update of {record_name}. It is already in desired state")
                return

        async with aiohttp.ClientSession() as session:
            # do we need to update a record, or create a new one?
            if record_name in self.zone_records.keys():
                if await self._update_record(session, record_name, self.zone_records[record_name]['record_id'], ip_address):
                    logging.info(f"Updated record for {record_name} ({ip_address})")
            else:
                if await self._create_record(session, record_name, ip_address):
                    logging.info(f"Created record for {record_name} ({ip_address})")

    async def _lookup_zone_id(self, session):
        """lookup zone id given zone name"""
        try:
            async with session.get(f"https://api.cloudflare.com/client/v4/zones?name={self.cloudflare_zone_name}", headers={"Authorization": f"Bearer {self.cloudflare_token}"}) as r:
                r.raise_for_status()
                zone_id = json.loads(await r.text())['result'][0]['id']
                logging.debug(f"Zone ID lookup finished: {zone_id}")
                return zone_id
        except Exception:
            logging.exception(f"Failed to look up zone id for {self.cloudflare_zone_name}")

    async def _get_records(self, session):
        """lookup records in zone"""
        try:
            total_pages, records = await self._get_records_page(session, 1)

            if total_pages > 1:
                for page in range(2, total_pages + 1):
                    records.update((await self._get_records_page(session, page))[1])

            logging.debug(f"Records lookup completed. Found {len(records)} total records")
            return records
        except Exception:
            logging.exception(f"Failed to retrieve records for zone {self.cloudflare_zone_name}")

    async def _get_records_page(self, session, page):
        """lookup records in zone on given page"""
        try:
            async with session.get(f"https://api.cloudflare.com/client/v4/zones/{self.zone_id}/dns_records?type=A&per_page=100&page={page}", headers={"Authorization": f"Bearer {self.cloudflare_token}"}) as r:
                r.raise_for_status()
                result = json.loads(await r.text())
                total_pages = result['result_info']['total_pages']

                records = result['result']
                records = { records[i]['name']:{ 'ip_address': records[i]['content'], 'record_id': records[i]['id'] } for i in range(0, len(records)) }
                logging.debug(f"Records lookup completed for page {page} of {total_pages}. Found {len(records)} records")
                return (total_pages, records)
        except Exception:
            logging.exception(f"Failed to retrieve records for zone {self.cloudflare_zone_name} (page {page})")

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

    # return if we failed to get zone_id or records since everything will fail
    if not await cf.setup():
        return

    tasks = []
    for vm in vms:
        if cloudflare_dns_subdomain:
            tasks.append(asyncio.create_task(cf.update_record(f"{vm['name']}.{cloudflare_dns_subdomain}.{cloudflare_zone}", vm['ip_address'])))
        else:
            tasks.append(asyncio.create_task(cf.update_record(f"{vm['name']}.{cloudflare_zone}", vm['ip_address'])))
    await asyncio.gather(*tasks)

async def pull_from_proxmox(proxmox_url, proxmox_nodes, proxmox_token_name, proxmox_token, ip_net_prefix):
    proxmox = Proxmox(proxmox_url, proxmox_nodes, proxmox_token_name, proxmox_token, ip_net_prefix)
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
    proxmox_nodes = [ node.strip() for node in config.get('proxmox', 'proxmox_nodes').split(',') if node.strip() != '' ]
    cloudflare_token = config.get('cloudflare', 'cloudflare_token')
    cloudflare_zone = config.get('cloudflare', 'cloudflare_zone')
    cloudflare_dns_subdomain = config.get('cloudflare', 'cloudflare_dns_subdomain', fallback=None)
except FileNotFoundError as err:
    logging.exception(f"Unable to read config file! Error: {err}")
    exit()
except Exception as err:
    logging.exception("Unable to parse config.ini or missing settings! Error: {err}")
    exit()

vms = asyncio.run(pull_from_proxmox(proxmox_url, proxmox_nodes, proxmox_token_name, proxmox_token, ip_net_prefix))
if vms:
    asyncio.run(sync_to_cloudflare(cloudflare_token, cloudflare_zone, cloudflare_dns_subdomain, vms))
else:
    logging.critical("Unable to get VM list from Proxmox")
