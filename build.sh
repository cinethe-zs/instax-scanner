#!/usr/bin/env bash
# build.sh — assemble instax-scanner_<version>_all.deb from project sources
# Usage:  ./build.sh [version]
# Requires: dpkg-deb (part of dpkg package, standard on Debian/Ubuntu)

set -e

VERSION="${1:-1.1.0}"
PKG_NAME="instax-scanner"
DEB_NAME="${PKG_NAME}_${VERSION}_all.deb"
BUILD_DIR="$(mktemp -d /tmp/instax-build-XXXXXX)"

echo "=== Building ${DEB_NAME} ==="
echo "    Build dir: ${BUILD_DIR}"

# ── Directory structure ────────────────────────────────────────────────────
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/lib/${PKG_NAME}"
mkdir -p "${BUILD_DIR}/usr/share/applications"
mkdir -p "${BUILD_DIR}/usr/share/icons/hicolor/128x128/apps"
mkdir -p "${BUILD_DIR}/usr/share/doc/${PKG_NAME}"

# ── Copy files ─────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "${SCRIPT_DIR}/src/instax_extract.py"       "${BUILD_DIR}/usr/lib/${PKG_NAME}/"
cp "${SCRIPT_DIR}/src/instax_gui.py"           "${BUILD_DIR}/usr/lib/${PKG_NAME}/"
cp "${SCRIPT_DIR}/debian/launcher"             "${BUILD_DIR}/usr/bin/${PKG_NAME}"
cp "${SCRIPT_DIR}/debian/postinst"             "${BUILD_DIR}/DEBIAN/postinst"
cp "${SCRIPT_DIR}/assets/instax-scanner.desktop" "${BUILD_DIR}/usr/share/applications/"
cp "${SCRIPT_DIR}/assets/instax-scanner.png"   "${BUILD_DIR}/usr/share/icons/hicolor/128x128/apps/"

# Minimal changelog + copyright
printf '' | gzip -9 > "${BUILD_DIR}/usr/share/doc/${PKG_NAME}/changelog.gz"
cat > "${BUILD_DIR}/usr/share/doc/${PKG_NAME}/copyright" << 'EOF'
instax-scanner — extract Instax photos from flatbed A4 scans.
License: MIT
EOF

# ── Permissions ────────────────────────────────────────────────────────────
find "${BUILD_DIR}" -type f -exec chmod 644 {} \;
find "${BUILD_DIR}" -type d -exec chmod 755 {} \;
chmod 755 "${BUILD_DIR}/usr/bin/${PKG_NAME}"
chmod 755 "${BUILD_DIR}/usr/lib/${PKG_NAME}/instax_gui.py"
chmod 755 "${BUILD_DIR}/DEBIAN/postinst"

# ── Generate control from template (update Installed-Size) ─────────────────
INST_SIZE=$(du -sk "${BUILD_DIR}/usr" | cut -f1)
sed "s/^Version:.*/Version: ${VERSION}/;
     s/^Installed-Size:.*/Installed-Size: ${INST_SIZE}/" \
    "${SCRIPT_DIR}/debian/control" > "${BUILD_DIR}/DEBIAN/control"

# ── Build ──────────────────────────────────────────────────────────────────
dpkg-deb --build --root-owner-group "${BUILD_DIR}" "${DEB_NAME}"
rm -rf "${BUILD_DIR}"

echo ""
echo "✓ ${DEB_NAME} ready."
echo ""
echo "Install with:"
echo "  sudo apt install python3-gi python3-opencv gir1.2-gtk-3.0"
echo "  sudo dpkg -i ${DEB_NAME}"
