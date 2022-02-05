# Proxmox-To-Cloudflare-Sync
Sync VM IP Addresses From Proxmox to Cloudflare Zone

# What It Does
This script will first get a list of all VMs in your configured Proxmox servers via the Proxmox API. It will try to pull the IP address for the VM. If it's unable to retrieve the IP address from the API, it will use the VMID to try to predict it. This assumes you are using a naming convention of `<network>.<vmid>` (for example: `192.168.1.<vmid>`).
Next, the CloudFlare API is accessed and a full copy of your supplied zone is downloaded. The zone is compared against the list of VMs and their IP addresses (either retrieved or predicted). If there are any discrepancies, the information from Proxmox is pushed up to CloudFlare.

# Work In Progress

**NOTICE:** This script and documentation are a work in progress. Use at your own risk. 

# Docker Setup
To Do

# Settings
## Main
- valid_networks: A comma-separated list of networks (with CIDR mask) that this script should consider to be "valid". If you supply `192.168.0.0/24,192.168.1.0/24`, but the script finds a network interface on a VM with an IP address of 10.55.66.77, it will not consider this valid, so it will not be pushed to CloudFlare.
- predict_network: This is a single network in CIDR notation (`10.55.66.0/24`). If a valid IP address is not found for a VM and one needs to be predicted, the script will append the VMID of the VM as the last octet in this network.
- predict_ip_addresses: Either `true` or `false` are valid here. This can be used to completely disable all IP address predictions for VMs.
- predict_ip_addresses_vmid_blacklist: A comma-separated list of VMIDs that should be excluded from prediction. If `predict_ip_addresses` is set to `false`, this setting is ignored.
- debug: Either `true` or `false`. Simply enables some extra debugging output for the script.

## Proxmox
- proxmox_url: The URL of your Proxmox server. If you have a cluster, you only need to supply a single node. Example: `https://your-proxmox-url:8006`
- proxmox_nodes: A comma-separated list of Proxmox node names that you would like this script to contact while discovering VMs.
- proxmox_token_name: The name of your Proxmox API token. Example: `api-user@pam!api-user`
- proxmox_token: Your Proxmox token value

## CloudFlare
- cloudflare_token: Your CloudFlare token value
- cloudflare_zone: The zone you would like to add `A` records to for your VMs. Example: `example.com`
- cloudflare_dns_subdomain: Optional sub-domain you would like added to your `A` records. For example, if set to "vm", records would be created like `server01.vm.domain.com`.
