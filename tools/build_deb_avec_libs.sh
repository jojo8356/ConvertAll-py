#!/usr/bin/env bash
# ConvertAll — .deb AUTONOME (« avec libs ») reconstruit depuis un asset déjà validé.
#
# Le .deb produit par release_qt6.sh est la variante LÉGÈRE (`Architecture: all`,
# sans PyQt6/Qt/Python, résolus par APT). Le code qui produisait la variante
# autonome (`Architecture: amd64`, runtime embarqué) a été retiré au commit
# 9216bf0 ; ce script la reconstruit sans toucher à l'arbre source validé : il
# repart du bundle portable signé/checksummé par la release.
#
# Usage (identité publique : angle brackets, ou les deux variables ci-dessous
# pour éviter tout caractère spécial selon le terminal) :
#   export CONVERTALL_MAINTAINER="Nom <email>"
#   export CONVERTALL_MAINTAINER_NAME="Nom"; export CONVERTALL_MAINTAINER_EMAIL="email"
#   bash tools/build_deb_avec_libs.sh <dossier dist/qt6-release/...> [version] [révision]
#
# Exemple :
#   bash tools/build_deb_avec_libs.sh \
#     dist/qt6-release/1699290b89765b7a36f3be26089a2876180fde84-20261014T074025Z-11298
#
# Codes de sortie : 0 = ok, 1 = échec, 2 = prérequis/arguments absents.
# N'exécute ni sudo, ni pip, ni apt ; ne pousse rien ; ne crée aucun tag.
set -euo pipefail

ASSETS=${1:?usage: bash tools/build_deb_avec_libs.sh <dossier dist/qt6-release/...> [version] [revision]}
VERSION=${2:-0.9.3}
REVISION=${3:-1}

MAINTAINER=${CONVERTALL_MAINTAINER:-}
if [ -z "$MAINTAINER" ] && [ -n "${CONVERTALL_MAINTAINER_NAME:-}" ] \
   && [ -n "${CONVERTALL_MAINTAINER_EMAIL:-}" ]; then
  MAINTAINER="$CONVERTALL_MAINTAINER_NAME <$CONVERTALL_MAINTAINER_EMAIL>"
fi
# Copier-coller depuis un rendu HTML : &lt; &gt; &amp; au lieu de < > &. On les
# rétablit plutôt que de refuser une identité par ailleurs valide.
MAINTAINER=${MAINTAINER//&lt;/<}
MAINTAINER=${MAINTAINER//&gt;/>}
MAINTAINER=${MAINTAINER//&amp;/\&}
[ -n "$MAINTAINER" ] || {
  echo 'exportez CONVERTALL_MAINTAINER="Nom <email>" (ou _NAME + _EMAIL)' >&2; exit 2; }

command -v dpkg-deb >/dev/null || { echo "dpkg-deb manquant (apt install dpkg)" >&2; exit 2; }
command -v readelf  >/dev/null || { echo "readelf manquant (apt install binutils)" >&2; exit 2; }
command -v tar      >/dev/null || { echo "tar manquant" >&2; exit 2; }

[[ "$VERSION"  =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version invalide: $VERSION" >&2; exit 2; }
[[ "$REVISION" =~ ^[0-9][A-Za-z0-9.+~]*$ ]] || { echo "révision invalide: $REVISION" >&2; exit 2; }
[[ "$MAINTAINER" =~ ^[^'<>']+\ \<[^\ @]+\@[^\ @]+\>$ ]] || { echo "CONVERTALL_MAINTAINER attendu sous la forme: Nom <email> (reçu: $MAINTAINER)" >&2; exit 2; }

TARBALL="$ASSETS/ConvertAll-$VERSION-qt6-linux-x86_64.tar.gz"
BUNDLE_NAME="ConvertAll-$VERSION-qt6-linux-x86_64"
[ -f "$TARBALL" ] || { echo "archive introuvable : $TARBALL" >&2; exit 2; }
sha256sum "$TARBALL"

# Le .deb doit être fabriqué à partir de l'archive réellement enregistrée par la
# release, pas d'un tarball voisin. Vérification quand release-provenance.json et
# python3 sont disponibles (sinon : avertissement, jamais de faux « vérifié »).
PROVENANCE="$ASSETS/release-provenance.json"
if [ -f "$PROVENANCE" ] && command -v python3 >/dev/null; then
  python3 - "$PROVENANCE" "$TARBALL" <<'PY'
import hashlib, json, sys
from pathlib import Path
manifest, archive = Path(sys.argv[1]), Path(sys.argv[2])
entry = json.loads(manifest.read_text(encoding='utf-8')).get('assets', {}).get(archive.name)
if entry is None:
    sys.exit(f'provenance: {archive.name} absent de release-provenance.json')
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
if digest != entry.get('sha256') or archive.stat().st_size != entry.get('bytes'):
    sys.exit(f'provenance: SHA-256/taille de {archive.name} différents du manifeste')
print(f'provenance: {archive.name} conforme au manifeste ({digest})')
PY
else
  echo "note : release-provenance.json absent ou python3 indisponible — archive non recoupée avec le manifeste"
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
tar -xzf "$TARBALL" -C "$WORK"
BUNDLE="$WORK/$BUNDLE_NAME"
[ -x "$BUNDLE/convertall" ] || { echo "bundle inattendu (pas de convertall exécutable) : $BUNDLE" >&2; exit 2; }

echo "== bundle : $(du -sh "$BUNDLE" | cut -f1) =="

ROOT="$WORK/deb-root"
mkdir -p "$ROOT/usr/lib" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/scalable/apps" "$ROOT/usr/share/doc/convertall" \
         "$ROOT/DEBIAN"
cp -a "$BUNDLE" "$ROOT/usr/lib/convertall"

# Lanceur identique à celui de l'ancien .deb amd64 (relocalisable, même extrait
# sans installation) : il ne cherche pas de Python dans le PATH.
cat > "$ROOT/usr/bin/convertall" <<'SH'
#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$HERE/../lib/convertall/convertall" "$@"
SH
chmod 755 "$ROOT/usr/bin/convertall"

cat > "$ROOT/usr/share/applications/convertall.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Version=1.1
Name=ConvertAll
GenericName=Unit Converter
GenericName[fr]=Convertisseur d’unités
Comment=Combine and convert units
Comment[fr]=Combiner et convertir les unités
Exec=convertall
Icon=convertall
Terminal=false
StartupNotify=true
Categories=Education;Math;
DESKTOP
chmod 644 "$ROOT/usr/share/applications/convertall.desktop"

# Icône et licences : pris dans le checkout courant s'il est là, sinon ignorés.
SOURCE_ROOT=${CONVERTALL_SOURCE_ROOT:-$PWD}
if [ -f "$SOURCE_ROOT/icons/convertall-icon.svg" ]; then
  cp "$SOURCE_ROOT/icons/convertall-icon.svg" "$ROOT/usr/share/icons/hicolor/scalable/apps/convertall.svg"
  for name in LICENSE LICENSE-GPL-3.0 LICENCES_QT6_FR.md; do
    [ -f "$SOURCE_ROOT/doc/$name" ] && cp "$SOURCE_ROOT/doc/$name" "$ROOT/usr/share/doc/convertall/$name"
  done
  cat > "$ROOT/usr/share/doc/convertall/copyright" <<'COPY'
ConvertAll: GPL-2.0-or-later; the PyQt6 binary combination is GPL-3.0.
Copyright notices and full terms: LICENSE and LICENSE-GPL-3.0.
Third-party notices: /usr/lib/convertall/doc/third-party/.
Corresponding application source accompanies this release.
Review third-party source/notice obligations before distribution.
COPY
  chmod 644 "$ROOT/usr/share/doc/convertall/copyright"
else
  echo "note : $SOURCE_ROOT/icons/convertall-icon.svg absent — icône/licences système non installées"
fi

# Niveau GLIBC réellement exigé par les ELF du bundle (pas l'étiquette du build host).
# `|| true` : readelf retourne un code non nul sur les fichiers non-ELF, et
# `find -exec … +` propage ce code (fatals avec pipefail + set -e).
GLIBC=$( { find "$BUNDLE" -type f -exec readelf --version-info {} + 2>/dev/null || true; } \
        | sed -n 's/.*GLIBC_\([0-9][0-9.]*\).*/\1/p' | sort -V | tail -1)
[ -n "$GLIBC" ] || { echo "aucun symbole GLIBC trouvé dans le bundle" >&2; exit 1; }
echo "== GLIBC requise : $GLIBC =="

INSTALLED_KIB=$(du -sk "$ROOT/usr" | cut -f1)

cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: convertall
Version: $VERSION-$REVISION
Architecture: amd64
Maintainer: $MAINTAINER
Section: science
Priority: optional
Installed-Size: $INSTALLED_KIB
Depends: libc6 (>= $GLIBC), libgcc-s1, libstdc++6, libgl1, libegl1, libxkbcommon0, libxkbcommon-x11-0, libdbus-1-3, libfontconfig1, libfreetype6, fonts-dejavu-core, libx11-6, libx11-xcb1, libxext6, libxrender1, libxcb1, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render0, libxcb-render-util0, libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-xfixes0, libxcb-xkb1, libwayland-client0, libwayland-cursor0, libwayland-egl1
Homepage: https://github.com/jojo8356/ConvertAll-py
Description: flexible unit converter (Python/PyQt6 edition)
 Combine arbitrary units, with translations, history and fractions.
 The Python and Qt6 runtimes are included in the private application
 directory: no python3-pyqt6 dependency is required.
CONTROL
chmod 644 "$ROOT/DEBIAN/control"

# Permissions canoniques de la release : dossiers 755, exécutables 755, reste 644.
find "$ROOT" -type d -exec chmod 755 {} +
find "$ROOT" -type f -perm -u+x -exec chmod 755 {} +
find "$ROOT" -type f ! -perm -u+x -exec chmod 644 {} +

DEB="$ASSETS/convertall_${VERSION}-${REVISION}_amd64.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$DEB"
dpkg-deb --info "$DEB"

# Fumigation : le paquet extrait doit démarrer (bundle embarqué, hors CI).
EXTRACT="$WORK/extract"
dpkg-deb --extract "$DEB" "$EXTRACT"
# QT_QPA_PLATFORM=offscreen : même environnement que la CI, fonctionne sans écran.
env QT_QPA_PLATFORM=offscreen "$EXTRACT/usr/bin/convertall" --version
env QT_QPA_PLATFORM=offscreen "$EXTRACT/usr/bin/convertall" --runtime-info | sed -n '1,12p'

( cd "$ASSETS" && sha256sum "$(basename "$DEB")" > "$(basename "$DEB").sha256" )
echo
echo "OK  $DEB"
echo "    $(cat "$DEB.sha256")"
