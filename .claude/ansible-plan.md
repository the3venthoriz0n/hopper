# Ansible Infrastructure Plan

## Goal

Replace imperative shell scripts (`server-setup-prod.sh`, one-time manual commands) with idempotent Ansible playbooks that run from GitHub Actions. Re-run safely at any time to enforce desired state.

## What Ansible Manages

| Task | Currently | With Ansible |
|------|-----------|--------------|
| Docker install + config | `server-setup-prod.sh` (manual) | `roles/docker` |
| Firewall (UFW) | `server-setup-prod.sh` (manual) | `roles/firewall` |
| App directories + permissions | Manual `mkdir -p` | `roles/app-dirs` |
| Docker network | Manual `docker network create` | `roles/docker-network` |
| GHCR auth | Manual `docker login` | `roles/registry-auth` |
| Log rotation (Docker daemon) | `deploy.sh` (every deploy, wasteful) | `roles/docker` |
| Disable system nginx | `server-setup-prod.sh` | `roles/docker` (ensure no conflicts) |
| Stripe setup | `scripts/setup_stripe.py` (run locally) | `roles/stripe` (wraps existing script) |
| Backup cron (prod) | `deploy.sh` (set on every deploy) | `roles/backups` |

## What Ansible Does NOT Manage

- Image builds (stays in CI)
- Container deployment / restarts (stays in `deploy.sh` via CI)
- Application secrets / .env files (stays in CI via GitHub Environment secrets)
- SSL certificates (stays in CI deploy step)

## Structure

```
ansible/
├── ansible.cfg
├── inventory/
│   ├── dev.yml              # Unraid host + vars
│   └── prod.yml             # DigitalOcean host + vars
├── playbooks/
│   ├── bootstrap.yml        # Full server setup (all roles)
│   └── stripe-setup.yml     # Stripe products/prices sync
├── roles/
│   ├── docker/
│   │   └── tasks/main.yml   # Install Docker, configure daemon, log rotation
│   ├── firewall/
│   │   └── tasks/main.yml   # UFW rules (prod only, skip on Unraid)
│   ├── app-dirs/
│   │   └── tasks/main.yml   # Create /opt/hopper-{env}, subdirs, permissions
│   ├── docker-network/
│   │   └── tasks/main.yml   # Ensure hopper_default network exists
│   ├── registry-auth/
│   │   └── tasks/main.yml   # docker login to GHCR
│   ├── backups/
│   │   └── tasks/main.yml   # Backup cron job (prod only)
│   └── stripe/
│       └── tasks/main.yml   # Run setup_stripe.py with correct env
└── requirements.yml         # Ansible Galaxy dependencies (if any)
```

## Inventory

```yaml
# inventory/dev.yml
all:
  hosts:
    unraid:
      ansible_host: "{{ lookup('env', 'DEV_SSH_HOST') }}"
      ansible_user: root
      ansible_ssh_private_key_file: /tmp/ssh_key
      hopper_env: dev
      app_dir: /opt/hopper-dev
      enable_firewall: false  # Unraid manages its own
      enable_backups: false
      docker_already_installed: true  # Unraid has Docker built-in

# inventory/prod.yml
all:
  hosts:
    digitalocean:
      ansible_host: "{{ lookup('env', 'PROD_SSH_HOST') }}"
      ansible_user: root
      ansible_ssh_private_key_file: /tmp/ssh_key
      hopper_env: prod
      app_dir: /opt/hopper-prod
      enable_firewall: true
      enable_backups: true
      docker_already_installed: false
```

## Key Roles

### docker
```yaml
# roles/docker/tasks/main.yml
- name: Install Docker (Debian/Ubuntu)
  when: not docker_already_installed
  block:
    - name: Install prerequisites
      apt:
        name: [ca-certificates, curl, gnupg]
        state: present

    - name: Add Docker GPG key
      apt_key:
        url: https://download.docker.com/linux/ubuntu/gpg

    - name: Add Docker repo
      apt_repository:
        repo: "deb https://download.docker.com/linux/ubuntu {{ ansible_distribution_release }} stable"

    - name: Install Docker packages
      apt:
        name: [docker-ce, docker-ce-cli, containerd.io, docker-buildx-plugin, docker-compose-plugin]
        state: present

    - name: Enable and start Docker
      systemd:
        name: docker
        enabled: true
        state: started

- name: Configure Docker daemon (log rotation)
  copy:
    content: |
      {"log-driver":"json-file","log-opts":{"max-size":"50m","max-file":"7"}}
    dest: /etc/docker/daemon.json
  notify: Reload Docker

- name: Disable system nginx if present
  systemd:
    name: nginx
    enabled: false
    state: stopped
  ignore_errors: true
```

### app-dirs
```yaml
# roles/app-dirs/tasks/main.yml
- name: Create app directory structure
  file:
    path: "{{ item }}"
    state: directory
    mode: '0755'
  loop:
    - "{{ app_dir }}"
    - "{{ app_dir }}/nginx"
    - "{{ app_dir }}/scripts"
    - "{{ app_dir }}/backups"
```

### docker-network
```yaml
# roles/docker-network/tasks/main.yml
- name: Ensure hopper_default network exists
  community.docker.docker_network:
    name: hopper_default
    state: present
```

### registry-auth
```yaml
# roles/registry-auth/tasks/main.yml
- name: Login to GHCR
  community.docker.docker_login:
    registry_url: ghcr.io
    username: "{{ ghcr_username }}"
    password: "{{ ghcr_token }}"
```

### firewall
```yaml
# roles/firewall/tasks/main.yml
- name: Configure UFW
  when: enable_firewall
  block:
    - name: Set default deny incoming
      community.general.ufw:
        direction: incoming
        default: deny

    - name: Set default allow outgoing
      community.general.ufw:
        direction: outgoing
        default: allow

    - name: Allow SSH
      community.general.ufw:
        rule: allow
        port: '22'
        proto: tcp

    - name: Allow HTTP
      community.general.ufw:
        rule: allow
        port: '80'
        proto: tcp

    - name: Allow HTTPS
      community.general.ufw:
        rule: allow
        port: '443'
        proto: tcp

    - name: Enable UFW
      community.general.ufw:
        state: enabled
```

### backups
```yaml
# roles/backups/tasks/main.yml
- name: Configure backup cron
  when: enable_backups
  cron:
    name: "hopper db backup"
    minute: "0"
    hour: "2"
    job: "{{ app_dir }}/scripts/backup-db.sh >> /var/log/hopper-db-backup.log 2>&1"
```

### stripe
```yaml
# roles/stripe/tasks/main.yml
- name: Run Stripe setup script
  command: python3 {{ app_dir }}/scripts/setup_stripe.py --env-file {{ hopper_env }}
  environment:
    STRIPE_SECRET_KEY: "{{ stripe_secret_key }}"
  register: stripe_result
  changed_when: "'Created' in stripe_result.stdout or 'Updated' in stripe_result.stdout"
```

## GitHub Actions Workflow

```yaml
# .github/workflows/infrastructure.yml
name: Infrastructure (Ansible)

on:
  workflow_dispatch:
    inputs:
      environment:
        description: 'Target environment'
        required: true
        type: choice
        options: [dev, prod]
      run_stripe:
        description: 'Also run Stripe setup'
        required: false
        default: false
        type: boolean

jobs:
  ansible:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    steps:
      - uses: actions/checkout@v5

      - name: Install Ansible
        run: pip install ansible community.docker community.general

      - name: Set up SSH key
        run: |
          echo "${{ secrets.SSH_KEY }}" > /tmp/ssh_key
          chmod 600 /tmp/ssh_key

      - name: Run bootstrap playbook
        env:
          DEV_SSH_HOST: ${{ secrets.SSH_HOST }}
          PROD_SSH_HOST: ${{ secrets.SSH_HOST }}
          GHCR_USERNAME: ${{ github.actor }}
          GHCR_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          ansible-playbook ansible/playbooks/bootstrap.yml \
            -i ansible/inventory/${{ inputs.environment }}.yml \
            -e "ghcr_username=$GHCR_USERNAME ghcr_token=$GHCR_TOKEN"

      - name: Run Stripe setup
        if: inputs.run_stripe
        run: |
          ansible-playbook ansible/playbooks/stripe-setup.yml \
            -i ansible/inventory/${{ inputs.environment }}.yml \
            -e "stripe_secret_key=${{ secrets.STRIPE_SECRET_KEY }}"
```

## Usage

### Bootstrap a new server
Actions → "Infrastructure (Ansible)" → Run workflow → select env → Run

### After changing infra config
Push changes to `ansible/` → manually trigger the workflow

### Stripe plan changes
Update `scripts/setup_stripe.py` → trigger workflow with "Also run Stripe setup" checked

## Migration Path

1. Scaffold `ansible/` directory structure
2. Write roles (adapt from existing `server-setup-prod.sh`)
3. Add `infrastructure.yml` workflow
4. Test on dev (Unraid) first
5. Test on prod (DigitalOcean)
6. Delete `scripts/server-setup-prod.sh`
7. Remove log rotation / cron setup from `deploy.sh` (Ansible handles it now)

## What Makes This Better

| Before | After |
|--------|-------|
| `server-setup-prod.sh` runs once, breaks if re-run | Ansible is idempotent — re-run safely anytime |
| Manual `docker login` on servers | Ansible ensures GHCR auth is always current |
| Backup cron set on every deploy (wasteful) | Set once, verified idempotently |
| No way to audit server state | Ansible playbook IS the documentation |
| Different manual steps for dev vs prod | Same playbook, different inventory |
| Stripe setup requires local venv | Runs in CI, uses environment secrets |
