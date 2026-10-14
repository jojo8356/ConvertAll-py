#!/usr/bin/env bash
# ConvertAll — AppImage autonome, reconstruite depuis le bundle déjà validé par
# une release. Même doctrine que tools/release_qt6.py :
#
#   * outils TÉLÉCHARGÉS PAR ID D'ASSET ET VÉRIFIÉS PAR SHA-256 (tools/appimage-lock.json),
#     jamais un « latest » flottant ;
#   * compression zstd imposée (le constructeur épinglé n'embarque que ce codec) ;
#   * AUCUN fichier portant la magie AppImage n'est exécuté si un intergiciel
#     binfmt_misc (AppImageLauncher…) la revendique : le contenu de l'image
#     produite est lu par offset (squashfs), puis l'AppRun extrait est exercé ;
#   * construction depuis un chemin local sans caractère non-ASCII (GLib).
#
# Usage :
#   bash tools/build_appimage.sh <dossier dist/qt6-release/...> [version] [--keep] [--debug]
#   bash tools/build_appimage.sh --self-check          # diagnostics hors ligne
#
# Exemple :
#   bash tools/build_appimage.sh \
#     dist/qt6-release/1699290b89765b7a36f3be26089a2876180fde84-20261014T074025Z-11298
#
# Variables : CONVERTALL_APPIMAGE_TOOLS_DIR (outils déjà téléchargés ; SHA-256 revérifié),
#             CONVERTALL_APPIMAGE_LOCK (défaut : tools/appimage-lock.json),
#             CONVERTALL_WORK_DIR (répertoire local ASCII, sinon /tmp)
#
# Codes de sortie : 0 = ok, 1 = échec, 2 = prérequis/arguments absents.
# N'exécute ni sudo, ni pip, ni apt ; ne pousse rien ; ne crée aucun tag.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
LOCK=${CONVERTALL_APPIMAGE_LOCK:-$REPO_ROOT/tools/appimage-lock.json}

# --- Lecture du payload : logique partagée (offset type 2 + copie brute) -----
read_offset() { # $1 = image ELF portant un payload squashfs -> offset sur stdout
  python3 - "$1" <<'PY'
import struct, sys
with open(sys.argv[1], 'rb') as stream:
    header = stream.read(64)
    if len(header) < 64 or header[:4] != b'\x7fELF' or header[4:6] != b'\x02\x01':
        sys.exit(f'{sys.argv[1]}: ce n’est pas un runtime AppImage ELF 64 bits')
    section_offset = struct.unpack_from('<Q', header, 40)[0]
    entry_size = struct.unpack_from('<H', header, 58)[0]
    section_count = struct.unpack_from('<H', header, 60)[0]
    if not (section_offset and entry_size and section_count):
        sys.exit(f'{sys.argv[1]}: table des sections absente')
    stream.seek(section_offset + entry_size * (section_count - 1))
    entry = stream.read(entry_size)
    if len(entry) < 64:
        sys.exit(f'{sys.argv[1]}: table des sections tronquée')
    table_end = section_offset + entry_size * section_count
    last_section_end = struct.unpack_from('<Q', entry, 24)[0] + struct.unpack_from('<Q', entry, 32)[0]
    offset = max(table_end, last_section_end)
    stream.seek(offset)
    magic = stream.read(4)
if magic != b'hsqs':
    sys.exit(f'{sys.argv[1]}: pas de payload squashfs à l’offset {offset} : {magic!r}')
print(offset)
PY
}

check_lock() { # valide le verrou et affiche une ligne par outil
  python3 - "$LOCK" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1], encoding='utf-8'))
if lock.get('compression') != 'zstd' or lock.get('architecture') != 'x86_64':
    sys.exit('verrou inattendu : compression/architecture non conformes')
for key in ('appimagetool', 'runtime'):
    pin = lock[key]
    if not isinstance(pin.get('asset_id'), int) or len(pin.get('sha256', '')) != 64:
        sys.exit(f'verrou invalide pour {key}')
    print(key, pin['repository'], pin['asset_id'], pin['name'], pin['sha256'])
PY
}

# --- Diagnostics hors ligne : verrou, outils hôtes, lecture d'un ELF --------
self_check() {
  echo "verrou : $LOCK"
  check_lock | while read -r kind repository asset_id name sha; do
    echo "  $kind : $repository#$asset_id ($name) $sha"
  done
  for tool in gh tar sha256sum unsquashfs python3; do
    if command -v "$tool" >/dev/null; then echo "  hôte : $tool OK"; else echo "  hôte : $tool MANQUANT"; fi
  done
  if [ -d /proc/sys/fs/binfmt_misc ] && grep -rlis 'appimage' /proc/sys/fs/binfmt_misc/* >/dev/null 2>&1; then
    echo "  binfmt_misc : gestionnaire AppImage présent — aucune image ne sera exécutée"
  else
    echo "  binfmt_misc : aucun gestionnaire AppImage"
  fi
  local sample work expected actual
  work=$(mktemp -d /tmp/convertall-selfcheck.XXXXXX)
  sample=$work/synthetic.AppImage
  # ELF 64 bits minimal : en-tête + table d'une section pointant plus loin que la
  # table, payload 'hsqs' à cet offset. read_offset() doit rendre exactement cet
  # offset, ce qui vérifie la règle « fin de la section la plus lointaine ».
  expected=$(python3 - "$sample" <<'PY'
import struct, sys
path = sys.argv[1]
section_offset, entry_size, section_count = 128, 64, 1
payload_offset = 256                              # après la table ET la section
header = bytearray(64)
header[0:4] = b'\x7fELF'
header[4:6] = b'\x02\x01'
struct.pack_into('<Q', header, 40, section_offset)
struct.pack_into('<H', header, 58, entry_size)
struct.pack_into('<H', header, 60, section_count)
entry = bytearray(entry_size)
struct.pack_into('<Q', entry, 24, payload_offset)  # sh_offset
struct.pack_into('<Q', entry, 32, 0)               # sh_size
data = bytearray(payload_offset + 36)
data[0:64] = header
data[section_offset:section_offset + entry_size] = entry
data[payload_offset:payload_offset + 4] = b'hsqs'
with open(path, 'wb') as stream:
    stream.write(data)
print(payload_offset)
PY
)
  actual=$(read_offset "$sample")
  rm -rf "$work"
  [ "$actual" = "$expected" ] || {
    echo "  lecture du payload : ÉCHEC (attendu $expected, obtenu $actual)" >&2; exit 1; }
  echo "  lecture du payload : offset $actual détecté correctement"
  echo "SELF-CHECK OK"
}

if [ "${1-}" = --self-check ]; then
  self_check
  exit $?
fi

ASSETS=${1:?usage: bash tools/build_appimage.sh <dossier dist/qt6-release/...> [version] [--keep] [--debug]}
VERSION=${2:-0.9.3}
shift $(( $# > 2 ? 2 : $# ))
KEEP=0; DEBUG=0
for option in "$@"; do
  case "$option" in
    --keep)  KEEP=1 ;;
    --debug) DEBUG=1 ;;
    *) echo "option inconnue : $option (attendu : --keep --debug)" >&2; exit 2 ;;
  esac
done
if [ "$DEBUG" = 1 ]; then set -x; fi

[ -f "$LOCK" ] || { echo "verrou d'outils introuvable : $LOCK" >&2; exit 2; }
TARBALL="$ASSETS/ConvertAll-$VERSION-qt6-linux-x86_64.tar.gz"
BUNDLE_NAME="ConvertAll-$VERSION-qt6-linux-x86_64"
[ -f "$TARBALL" ] || { echo "bundle portable introuvable : $TARBALL" >&2; exit 2; }
for tool in gh tar sha256sum unsquashfs python3; do
  command -v "$tool" >/dev/null || { echo "$tool manquant (apt install squashfs-tools gh binutils)" >&2; exit 2; }
done

sha256sum "$TARBALL"
PROVENANCE="$ASSETS/release-provenance.json"
if [ -f "$PROVENANCE" ]; then
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
  echo "note : release-provenance.json absent — bundle non recoupé avec le manifeste"
fi

# --- Répertoire de travail local et ASCII -----------------------------------
if [ -n "${CONVERTALL_WORK_DIR:-}" ]; then
  work=$CONVERTALL_WORK_DIR
else
  work=$(mktemp -d /tmp/convertall-appimage.XXXXXX)
fi
mkdir -p "$work" "$work/home"
trap '[ "$KEEP" = 1 ] || rm -rf "$work"' EXIT
python3 -c 'import sys; raise SystemExit(0 if sys.argv[1].isascii() else 2)' "$work" || {
  echo "CONVERTALL_WORK_DIR doit être en ASCII (appimagetool passe ses arguments par GLib) : $work" >&2
  exit 2; }
tools="$work/tools"
mkdir -p "$tools"

fetch_pin() { # $1 kind $2 dépôt $3 asset_id $4 nom $5 sha256 -> chemin sur stdout
  local kind=$1 repository=$2 asset_id=$3 name=$4 sha=$5 path="$tools/$4" actual
  if [ -n "${CONVERTALL_APPIMAGE_TOOLS_DIR:-}" ] && [ -f "$CONVERTALL_APPIMAGE_TOOLS_DIR/$name" ]; then
    cp "$CONVERTALL_APPIMAGE_TOOLS_DIR/$name" "$path"
    echo "outil réutilisé : $name" >&2
  else
    echo "téléchargement épinglé : $name (asset $asset_id de $repository)" >&2
    gh api "repos/$repository/releases/assets/$asset_id" -H 'Accept: application/octet-stream' \
       > "$path" || { echo "téléchargement impossible (asset retiré ?) — ne jamais le remplacer par un binaire 'latest'" >&2; exit 1; }
  fi
  actual=$(sha256sum "$path" | cut -d' ' -f1)
  [ "$actual" = "$sha" ] || { echo "SHA-256 de $name non conforme au verrou ($actual)" >&2; exit 1; }
  head -c 4 "$path" | od -An -c | tr -d ' \n' | grep -q '177ELF' \
    || { echo "$name n'est pas un ELF — refus d'exécution" >&2; exit 1; }
  chmod 755 "$path"
  printf '%s\n' "$path"
}

pins=$(check_lock)
tool_path=$(printf '%s\n' "$pins" | awk '$1=="appimagetool" {print $2, $3, $4, $5}' \
            | { read -r r a n s; fetch_pin appimagetool "$r" "$a" "$n" "$s"; })
runtime_path=$(printf '%s\n' "$pins" | awk '$1=="runtime" {print $2, $3, $4, $5}' \
               | { read -r r a n s; fetch_pin runtime "$r" "$a" "$n" "$s"; })
echo "appimagetool : $tool_path"
echo "runtime      : $runtime_path"

# --- Intergiciel binfmt_misc : peut-on exécuter la magie AppImage ? ---------
handler=0
if [ -d /proc/sys/fs/binfmt_misc ] && grep -rlis 'appimage' /proc/sys/fs/binfmt_misc/* >/dev/null 2>&1; then
  handler=1
  echo "[appimage] un gestionnaire binfmt_misc revendique les AppImage :" >&2
  grep -rlis 'appimage' /proc/sys/fs/binfmt_misc/* 2>/dev/null | sed 's/^/  /' >&2 || true
  echo "[appimage] aucun fichier portant la magie ne sera exécuté (ces gestionnaires ne lisent pas notre payload zstd)." >&2
  echo '[appimage] test de double-clic réel : sudo systemctl stop appimagelauncherd' >&2
else
  echo "[appimage] aucun gestionnaire binfmt_misc AppImage détecté" >&2
fi

extract_payload() { # $1 image $2 destination $3 fichier attendu -> destination
  local image=$1 destination=$2 required=$3 offset payload
  offset=$(read_offset "$image")
  payload="$work/payload.squashfs"
  python3 - "$image" "$payload" "$offset" <<'PY'
import shutil, sys
from pathlib import Path
image, payload, offset = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
with image.open('rb') as source, payload.open('wb') as target:
    source.seek(offset)
    shutil.copyfileobj(source, target)
PY
  rm -rf "$destination"
  unsquashfs -q -d "$destination" "$payload" >/dev/null
  rm -f "$payload"
  [ -e "$destination/$required" ] || { echo "$required absent de $image" >&2; exit 1; }
  printf '%s\n' "$destination"
}

extract_tool() { # $1 AppImage d'outil -> chemin d'AppRun sur stdout
  local root="$work/tool-root"
  rm -rf "$root" "$work/squashfs-root"
  if [ "$handler" = 0 ]; then
    if ( cd "$work" && "$1" --appimage-extract >/dev/null 2>&1 ) && [ -e "$work/squashfs-root/AppRun" ]; then
      mv "$work/squashfs-root" "$root"
      printf '%s\n' "$root/AppRun"
      return 0
    fi
    echo "[appimage] extraction via le runtime impossible — lecture directe du payload" >&2
    rm -rf "$work/squashfs-root"
  fi
  extract_payload "$1" "$root" AppRun >/dev/null
  printf '%s\n' "$root/AppRun"
}

tool=$(extract_tool "$tool_path")
echo "constructeur extrait : $tool"

# --- AppDir : même contenu que stage_appdir() de linux_release.py -----------
tar -xzf "$TARBALL" -C "$work"
bundle="$work/$BUNDLE_NAME"
[ -x "$bundle/convertall" ] || { echo "bundle inattendu : $bundle" >&2; exit 1; }

appdir="$work/ConvertAll.AppDir"
rm -rf "$appdir"
mkdir -p "$appdir/usr/lib"
cp -a "$bundle" "$appdir/usr/lib/convertall"
cat > "$appdir/AppRun" <<'APPRUN'
#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec "$HERE/usr/lib/convertall/convertall" "$@"
APPRUN
cat > "$appdir/convertall.desktop" <<'DESKTOP'
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
cp "$REPO_ROOT/icons/convertall-icon.svg" "$appdir/convertall.svg"
cp "$REPO_ROOT/icons/convertall_lg.png"  "$appdir/convertall.png"
cp "$REPO_ROOT/icons/convertall_lg.png"  "$appdir/.DirIcon"
find "$appdir" -type d -exec chmod 755 {} +
find "$appdir" -type f -perm -u+x -exec chmod 755 {} +
find "$appdir" -type f ! -perm -u+x -exec chmod 644 {} +
command -v desktop-file-validate >/dev/null && desktop-file-validate "$appdir/convertall.desktop"

# --- Construction avec le constructeur ET le runtime épinglés ---------------
runtime_argument="$work/runtime-x86_64"
cp "$runtime_path" "$runtime_argument"
[ "$(sha256sum "$runtime_argument" | cut -d' ' -f1)" = "$(sha256sum "$runtime_path" | cut -d' ' -f1)" ] \
  || { echo "runtime copié non conforme au verrou" >&2; exit 1; }

image="$ASSETS/ConvertAll-$VERSION-x86_64.AppImage"
built="$work/$(basename "$image")"
rm -f "$built" "$image"
echo "construction de $image (zstd, runtime épinglé)…"
( cd "$work" && env ARCH=x86_64 VERSION="$VERSION" LC_ALL=C.UTF-8 \
    "$tool" --runtime-file "$runtime_argument" --comp zstd --no-appstream "$appdir" "$built" )
[ -f "$built" ] || { echo "appimagetool n'a produit aucune image" >&2; exit 1; }
mv "$built" "$image"
chmod 755 "$image"

python3 - "$image" <<'PY'
import sys
with open(sys.argv[1], 'rb') as stream:
    header = stream.read(11)
if header[8:11] != b'AI\x02':
    sys.exit(f'{sys.argv[1]}: magie AppImage absente (AI\\002 à l’offset 8)')
PY
sha256sum "$image"

# --- Acceptation : on lit le contenu de l'image, sans jamais l'exécuter -----
extracted=$(extract_payload "$image" "$work/image-root" AppRun)
echo "[acceptation] payload lu par offset, AppRun extrait — l'image n'a pas été exécutée"
env QT_QPA_PLATFORM=offscreen HOME="$work/home" "$extracted/AppRun" --version
env QT_QPA_PLATFORM=offscreen HOME="$work/home" "$extracted/AppRun" --runtime-info | sed -n '1,8p'
env QT_QPA_PLATFORM=offscreen HOME="$work/home" "$extracted/AppRun" -q 1 in cm

( cd "$ASSETS" && sha256sum "$(basename "$image")" > "$(basename "$image").sha256" )
echo
echo "OK  $image"
echo "    $(cat "$image.sha256")"
echo
echo "Acceptation manuelle restante : double-clic réel dans un bureau (DPI/GPU),"
echo "après avoir arrêté tout intergiciel : sudo systemctl stop appimagelauncherd"
