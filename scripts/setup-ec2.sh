#!/usr/bin/env bash
# Idempotent setup script for an Amazon Linux 2023 EC2 instance.
# Installs: gh CLI, Docker, Claude Code, Tailscale, Superset CLI.
#
# Usage (on the EC2 host):
#   chmod +x setup-ec2.sh && ./setup-ec2.sh
#
# Re-running is safe — every step checks for an existing install.

set -euo pipefail

# ---------- helpers ----------
log()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '    \033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '    \033[1;33m!\033[0m %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------- preflight ----------
if [[ "$(id -u)" -eq 0 ]]; then
  echo "Run as ec2-user, not root. Aborting." >&2
  exit 1
fi

if ! grep -q 'Amazon Linux 2023' /etc/os-release; then
  warn "Not detected as Amazon Linux 2023 — continuing anyway."
fi

log "Updating system packages"
sudo dnf -y -q update
sudo dnf -y -q install dnf-plugins-core curl tar git
ok "Base packages ready"

# ---------- gh CLI ----------
log "Installing GitHub CLI (gh)"
if have gh; then
  ok "gh already installed: $(gh --version | head -1)"
else
  sudo dnf -y config-manager --add-repo https://cli.github.com/packages/rpm/gh-cli.repo
  sudo dnf -y install gh
  ok "gh installed: $(gh --version | head -1)"
fi

# ---------- Docker ----------
log "Installing Docker"
if have docker; then
  ok "docker already installed: $(docker --version)"
else
  sudo dnf -y install docker
  ok "docker installed: $(docker --version)"
fi

sudo systemctl enable --now docker
if id -nG "$USER" | grep -qw docker; then
  ok "User '$USER' already in docker group"
else
  sudo usermod -aG docker "$USER"
  warn "Added '$USER' to docker group — log out and back in (or run 'newgrp docker') for it to take effect."
fi

# ---------- Tailscale ----------
log "Installing Tailscale"
if have tailscale; then
  ok "tailscale already installed: $(tailscale version | head -1)"
else
  sudo dnf -y config-manager --add-repo https://pkgs.tailscale.com/stable/amazon-linux/2023/tailscale.repo
  sudo dnf -y install tailscale
  ok "tailscale installed: $(tailscale version | head -1)"
fi
sudo systemctl enable --now tailscaled
ok "tailscaled running"

# ---------- Claude Code ----------
log "Installing Claude Code"
if have claude; then
  ok "claude already installed: $(claude --version 2>/dev/null || echo 'present')"
else
  curl -fsSL https://claude.ai/install.sh | bash
  # Native installer drops the binary in ~/.local/bin
  if ! grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"
  fi
  export PATH="$HOME/.local/bin:$PATH"
  if have claude; then
    ok "claude installed: $(claude --version 2>/dev/null || echo 'present')"
  else
    warn "claude binary not on PATH yet — open a new shell or 'source ~/.bashrc'."
  fi
fi

# ---------- Superset CLI ----------
log "Installing Superset CLI"
if have superset; then
  ok "superset already installed: $(superset --version 2>/dev/null || echo 'present')"
else
  curl -fsSL https://superset.sh/cli/install.sh | sh
  if have superset; then
    ok "superset installed: $(superset --version 2>/dev/null || echo 'present')"
  else
    warn "superset binary not on PATH yet — open a new shell."
  fi
fi

# ---------- summary ----------
cat <<'EOF'

============================================================
 Install complete. Next steps (interactive):
============================================================
  1. Docker group       : log out & back in, or run:  newgrp docker
                          then verify:               docker run --rm hello-world
  2. GitHub CLI         : gh auth login
  3. Tailscale          : sudo tailscale up            # prints a login URL
  4. Claude Code        : claude  (will prompt to log in on first run)
  5. Superset           : superset  (follow first-run instructions)

If 'claude' or 'superset' is not found, open a new shell or run:
  source ~/.bashrc
============================================================
EOF
