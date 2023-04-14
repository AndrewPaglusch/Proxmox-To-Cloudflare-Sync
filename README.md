# Proxmox Cloudflare Sync

This application queries your Proxmox node(s) to retrieve a list of all VMs. It attempts to determine each VM's IP address and subsequently updates the corresponding A records on Cloudflare. If the VM's IP address cannot be discovered, the application generates a predicted IP address based on the VM's VMID, using it as the last octet of an IP address within the specified NETWORK range. This predicted IP address is then used to create or update the A record on Cloudflare, ensuring that the DNS records remain up-to-date even when the IP address of a VM cannot be directly determined.

This tool is perfect for users who manage dynamic Proxmox VM environments and want to keep their Cloudflare DNS records current with minimal manual effort.

## Prerequisites

- Docker and Docker Compose installed on the host
- A Proxmox cluster with API access
- A Cloudflare account with API access

## Environment Variables

- `DEBUG`: Set to "true" to enable debug logging. Default is "false".
- `NETWORK`: The network range (CIDR notation) within which the VMs' IP addresses are expected to be discovered, e.g., `192.168.2.0/24`. Any dicovered IP addresses that are outside of this range are ignored. This is also the network used when a predicted IP address must be created for a VM.
- `PROXMOX_URL`: The URL of your Proxmox server, e.g., `https://proxmox-server:8006`.
- `PROXMOX_NODES_LIST`: A comma-separated list of Proxmox node names, e.g., `pve01,pve02`.
- `PROXMOX_TOKEN_NAME`: The name of the Proxmox API token, e.g., `api-user@pam!main`.
- `PROXMOX_TOKEN`: The Proxmox API token.
- `CLOUDFLARE_TOKEN`: The Cloudflare API token.
- `CLOUDFLARE_ZONE`: The domain name managed by Cloudflare, e.g., `mydomain.net`.
- `CLOUDFLARE_DNS_SUBDOMAIN`: (Optional) The subdomain for the A records, e.g., `nyc`. If not provided, the A records will be created directly under the main domain.
- `INTERVAL`: (Optional) The time interval between sync attempts, e.g., `1h`. Default is `1h`.

## Deployment

1. Clone the repository to your server:
```bash
git clone https://github.com/AndrewPaglusch/Proxmox-To-Cloudflare-Sync.git
cd Proxmox-To-Cloudflare-Sync/
```
2. Edit the `docker-compose.yml` file and set the environment variables as needed.
3. Start the container using Docker Compose:
```bash
docker-compose up -d
```
