#!/bin/bash

# =============================================================================
# BLOODSPIRE Arena Linux Installer
# =============================================================================

# 1. Request Root Privileges
if [ "$EUID" -ne 0 ]; then 
  echo "Please run as root (use sudo ./bloodspire_linux_installer.sh)"
  exit
fi

DEST_DIR="/opt/bloodspire_arena"
HTML_FILE="bloodspire_client.html"
ICON_FILE="BloodspireIcon.ico"
INVITE_URL="https://login.tailscale.com/admin/invite/tZAoQihKH8jNKFKemrA311"

echo "------------------------------------------------"
echo "        BLOODSPIRE ARENA INSTALLER v1.0         "
echo "------------------------------------------------"

# 2. Create Directory
if [ ! -d "$DEST_DIR" ]; then
    echo "[*] Creating directory $DEST_DIR..."
    mkdir -p "$DEST_DIR"
fi

# 3. Deploy Files
if [ -f "$HTML_FILE" ]; then
    echo "[*] Deploying $HTML_FILE..."
    cp "$HTML_FILE" "$DEST_DIR/"
    chmod 644 "$DEST_DIR/$HTML_FILE"
else
    echo "[!] Error: $HTML_FILE not found in the current directory."
fi

if [ -f "$ICON_FILE" ]; then
    cp "$ICON_FILE" "$DEST_DIR/"
fi

# 4. Install Tailscale
echo "[*] Checking for Tailscale..."
if ! command -v tailscale &> /dev/null; then
    echo "[*] Tailscale not found. Installing via official script..."
    curl -fsSL https://tailscale.com/install.sh | sh
else
    echo "[+] Tailscale is already installed."
fi

# 5. Instructions and Invite Link
echo ""
echo "------------------------------------------------"
echo "TAILSCALE SETUP INSTRUCTIONS:"
echo "1. Run 'sudo tailscale up' in your terminal."
echo "2. Follow the link provided in the terminal to log in."
echo "------------------------------------------------"
echo ""

read -p "Would you like to join the Bloodspire Arena Server now? (y/n): " choice
if [[ "$choice" == "y" || "$choice" == "Y" ]]; then
    # Attempts to open the link in the default browser
    xdg-open "$INVITE_URL" || echo "Please open this link manually: $INVITE_URL"
fi

# 6. Create Desktop Shortcut (Standard Linux .desktop file)
DESKTOP_PATH="/usr/share/applications/bloodspire.desktop"
echo "[*] Creating desktop shortcut..."

cat <<EOF > "$DESKTOP_PATH"
[Desktop Entry]
Version=1.0
Type=Application
Name=Bloodspire Arena
Comment=Launch the Bloodspire Arena Client
Exec=xdg-open $DEST_DIR/$HTML_FILE
Icon=$DEST_DIR/$ICON_FILE
Terminal=false
Categories=Game;
EOF

# Copy to user's personal desktop if it exists
USER_DESKTOP=$(sudo -u $SUDO_USER xdg-user-dir DESKTOP)
if [ -d "$USER_DESKTOP" ]; then
    cp "$DESKTOP_PATH" "$USER_DESKTOP/"
    chown $SUDO_USER:$SUDO_USER "$USER_DESKTOP/bloodspire.desktop"
    chmod +x "$USER_DESKTOP/bloodspire.desktop"
fi

echo "------------------------------------------------"
echo "             INSTALL COMPLETE                 "
echo "------------------------------------------------"
echo "Your client is located at: $DEST_DIR/$HTML_FILE"
echo "Press Enter to exit..."
read