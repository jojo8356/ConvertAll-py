#!/usr/bin/env bash
# ConvertAll — .deb OPTIMISÉ (« sans libs ») : paquet léger, Architecture: all.
#
# Variante recommandée : code + ressources seulement, `Depends` résolu par APT
# (python3-pyqt6, python3-pyqt6.sip, qt6-translations-l10n). Aucun ELF, aucun
# PyQt6/Qt/libpython embarqué. C'est le paquet que `release_qt6.sh` publie déjà ;
# ce script le reconstruit localement depuis l'archive source de la release
# (SHA-256 recoupé avec release-provenance.json) ou, à défaut, depuis un checkout.
#
# Usage :
#   export CONVERTALL_MAINTAINER_NAME="Nom" ; export CONVERTALL_MAINTAINER_EMAIL="email"
#   # ou :  export CONVERTALL_MAINTAINER="Nom <email>"
#   bash tools/build_deb_leger.sh <dossier dist/qt6-release/... | ''> [version] [révision]
#
# Exemples :
#   bash tools/build_deb_leger.sh dist/qt6-release/1699290b89765b7a36f3be26089a2876180fde84-20261014T074025Z-11298
#   bash tools/build_deb_leger.sh '' 0.9.3 2          # depuis le checkout courant
#
# Variables : CONVERTALL_SOURCE_ROOT (checkout de repli ; défaut : racine du dépôt)
#
# Codes de sortie : 0 = ok, 1 = échec, 2 = prérequis/arguments absents.
# N'exécute ni sudo, ni pip, ni apt ; ne pousse rien ; ne crée aucun tag.
# Le paquet produit N'EMBARQUE RIEN : il ne démarre que sur une machine ayant
# déjà python3-pyqt6/qt6-translations-l10n (le test de fumée le détecte).
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ASSETS=${1-}
VERSION=${2:-0.9.3}
REVISION=${3:-1}
SOURCE_ROOT=${CONVERTALL_SOURCE_ROOT:-$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)}

maintainer=${CONVERTALL_MAINTAINER:-}
if [ -z "$maintainer" ] && [ -n "${CONVERTALL_MAINTAINER_NAME:-}" ] \
   && [ -n "${CONVERTALL_MAINTAINER_EMAIL:-}" ]; then
  maintainer="$CONVERTALL_MAINTAINER_NAME <$CONVERTALL_MAINTAINER_EMAIL>"
fi
# Copier-coller depuis un rendu HTML : &lt; &gt; &amp; au lieu de < > &.
maintainer=${maintainer//&lt;/<}
maintainer=${maintainer//&gt;/>}
maintainer=${maintainer//&amp;/\&}
[ -n "$maintainer" ] || { echo 'exportez CONVERTALL_MAINTAINER_NAME + CONVERTALL_MAINTAINER_EMAIL' >&2; exit 2; }
[[ "$maintainer" =~ ^[^'<>']+\ \<[^\ @]+\@[^\ @]+\>$ ]] || { echo "identité attendue: Nom <email> (reçu: $maintainer)" >&2; exit 2; }
[[ "$VERSION"  =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "version invalide: $VERSION" >&2; exit 2; }
[[ "$REVISION" =~ ^[0-9][A-Za-z0-9.+~]*$ ]] || { echo "révision invalide: $REVISION" >&2; exit 2; }
command -v dpkg-deb >/dev/null || { echo "dpkg-deb manquant (apt install dpkg)" >&2; exit 2; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# --- 1. Source : archive de la release (vérifiée) sinon checkout -------------
archive=""
[ -n "$ASSETS" ] && archive="$ASSETS/ConvertAll-$VERSION-qt6-source.tar.gz"
if [ -n "$archive" ] && [ -f "$archive" ]; then
  sha256sum "$archive"
  provenance="$ASSETS/release-provenance.json"
  if [ -f "$provenance" ] && command -v python3 >/dev/null; then
    python3 - "$provenance" "$archive" <<'PY'
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
    echo "note : release-provenance.json absent — archive source non recoupée avec le manifeste"
  fi
  tar -xzf "$archive" -C "$work"
  SOURCE_ROOT=$(find "$work" -maxdepth 3 -type f -name convertall.py -path '*/source/*' -printf '%h/..\n' | head -1)
  [ -n "$SOURCE_ROOT" ] || { echo "structure d'archive source inattendue" >&2; exit 1; }
  echo "source : archive $archive"
else
  [ -f "$SOURCE_ROOT/source/convertall.py" ] || {
    echo "ni archive source dans '$ASSETS', ni checkout dans '$SOURCE_ROOT'" >&2; exit 2; }
  echo "source : checkout $SOURCE_ROOT"
  if [ -d "$SOURCE_ROOT/.git" ] && [ -n "$(git -C "$SOURCE_ROOT" status --porcelain)" ]; then
    echo "AVERTISSEMENT : checkout modifié (arbre non propre) — le paquet ne sera pas traçable à un SHA."
  fi
fi

found=$(sed -n "s/^__version__ = '\([0-9.]*\)'$/\1/p" "$SOURCE_ROOT/source/convertall.py" | head -1)
[ "$found" = "$VERSION" ] || { echo "version de la source ($found) différente de celle demandée ($VERSION)" >&2; exit 2; }

# --- 2. Staging : code + ressources seulement (aucun runtime) ---------------
root="$work/deb-root"
app="$root/usr/share/convertall"
mkdir -p "$app/data" "$app/icons" "$app/translations" \
         "$root/usr/bin" "$root/usr/share/applications" \
         "$root/usr/share/icons/hicolor/scalable/apps" "$root/usr/share/doc/convertall" "$root/DEBIAN"

for file in "$SOURCE_ROOT"/source/*.py; do
  [ "$(basename "$file")" = setup.py ] && continue
  cp "$file" "$app/"
done
cp "$SOURCE_ROOT"/data/*.dat "$app/data/"
cp "$SOURCE_ROOT"/icons/*.png "$app/icons/"
cp "$SOURCE_ROOT"/translations/convertall_*.qm "$app/translations/"

cat > "$app/_debian_entry.py" <<'PY'
from pathlib import Path
import sys
try:
    import convertall
except ImportError as error:
    print("Debian dependencies unavailable: " + str(error) + "\n"
          "Install with apt: python3-pyqt6 python3-pyqt6.sip qt6-translations-l10n", file=sys.stderr)
    sys.exit(1)
base = Path(__file__).resolve().parent
convertall.dataFilePath = str(base / "data")
convertall.iconPath = str(base / "icons")
convertall.helpFilePath = str(base.parent / "doc" / "convertall")
sys.exit(convertall.main())
PY

# Interpréteur système figé : -E/-s empêchent un venv/PYTHONPATH/utilisateur
# de faire passer pour « système » un environnement non Debian.
cat > "$root/usr/bin/convertall" <<'SH'
#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/python3 -E -s "$HERE/../share/convertall/_debian_entry.py" "$@"
SH
chmod 755 "$root/usr/bin/convertall"

cat > "$root/usr/share/applications/convertall.desktop" <<'DESKTOP'
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
chmod 644 "$root/usr/share/applications/convertall.desktop"

[ -f "$SOURCE_ROOT/icons/convertall-icon.svg" ] && \
  cp "$SOURCE_ROOT/icons/convertall-icon.svg" "$root/usr/share/icons/hicolor/scalable/apps/convertall.svg"
for pattern in 'README*.html' 'LICENSE*'; do
  for file in "$SOURCE_ROOT"/doc/$pattern; do
    [ -f "$file" ] && cp "$file" "$root/usr/share/doc/convertall/"
  done
done
cat > "$root/usr/share/doc/convertall/copyright" <<'COPY'
ConvertAll: GPL-2.0-or-later; use with PyQt6 under GPLv3.
Copyright notices and full terms: LICENSE and LICENSE-GPL-3.0.
Only application source and resources are distributed here.
Python, Qt, PyQt6 and SIP are dependencies managed by Debian.
COPY
chmod 644 "$root/usr/share/doc/convertall/copyright"

# --- 3. Contrôles de non-embarquement (mêmes règles que la release) ---------
while IFS= read -r -d '' path; do
  name=$(basename "$path")
  case "$name" in
    PyQt6|_internal|base_library.zip|third-party|setup.py|*.dist-info|*.egg-info|*.so|*.pyd|*.dll|*.pyc|*.exe|*.ts|*.spec|libpython*|libQt6*|libqt6*)
      echo "fichier de runtime/build interdit dans le paquet léger : $path" >&2; exit 1 ;;
  esac
  if [ -f "$path" ] && [ "$(head -c 4 "$path" | od -An -c | tr -d ' \n')" = '177ELF' ]; then
    echo "binaire ELF dans un paquet Architecture: all : $path" >&2; exit 1
  fi
done < <(find "$root" -type f -print0)

count_dat=$(find "$app/data" -name '*.dat' | wc -l)
count_qm=$(find "$app/translations" -name 'convertall_*.qm' | wc -l)
[ "$count_dat" -eq 7 ] || { echo "7 catalogues d'unités attendus, trouvés : $count_dat" >&2; exit 1; }
[ "$count_qm" -eq 6 ] || { echo "6 traductions applicatives attendues, trouvées : $count_qm" >&2; exit 1; }
[ -f "$app/convertall.py" ] || { echo "convertall.py manquant" >&2; exit 1; }

installed_kib=$(du -sk "$root/usr" | cut -f1)
cat > "$root/DEBIAN/control" <<CONTROL
Package: convertall
Version: $VERSION-$REVISION
Architecture: all
Maintainer: $maintainer
Section: science
Priority: optional
Installed-Size: $installed_kib
Depends: python3 (>= 3.11), python3-pyqt6 (>= 6.4.2), python3-pyqt6.sip (>= 13.4.1), qt6-translations-l10n (>= 6.4.2)
Homepage: https://github.com/jojo8356/ConvertAll-py
Description: flexible unit converter (Python/PyQt6 edition)
 Combine arbitrary units, with translations, history and fractions.
 Python, PyQt6, SIP and Qt are supplied by Debian packages, not bundled.
CONTROL
chmod 644 "$root/DEBIAN/control"

find "$root" -type d -exec chmod 755 {} +
find "$root" -type f -perm -u+x -exec chmod 755 {} +
find "$root" -type f ! -perm -u+x -exec chmod 644 {} +

# --- 4. Construction : xz -9, comme la release -------------------------------
outdir=${ASSETS:-$SOURCE_ROOT/dist/debian}
mkdir -p "$outdir"
deb="$outdir/convertall_${VERSION}-${REVISION}_all.deb"
dpkg-deb --root-owner-group -Zxz -z9 --build "$root" "$deb"
dpkg-deb --info "$deb" | sed -n '1,20p'

# --- 5. Fumée : seulement si le runtime système est réellement présent ------
if python3 -c 'import PyQt6' 2>/dev/null; then
  extract="$work/extract"
  dpkg-deb --extract "$deb" "$extract"
  env QT_QPA_PLATFORM=offscreen "$extract/usr/bin/convertall" --version
else
  echo "note : python3-pyqt6 absent de CETTE machine — test de fumée sauté."
  echo "       Sur la machine cible : sudo apt install python3-pyqt6 python3-pyqt6.sip qt6-translations-l10n"
fi

( cd "$outdir" && sha256sum "$(basename "$deb")" > "$(basename "$deb").sha256" )
echo
echo "OK  $deb"
echo "    $(cat "$deb.sha256")"
