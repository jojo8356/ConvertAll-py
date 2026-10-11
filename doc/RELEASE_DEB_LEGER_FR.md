# Release Debian « légère » — commandes

Produit `convertall_<version>-1_all.deb` (environ **240 Ko** au lieu de 42 Mo).
Rien n'est embarqué : **toute dépendance déjà présente dans les dépôts
Debian/Ubuntu devient un `Depends:`**, Python 3, PyQt6 et Qt6 viennent d'APT.
Aucun PyInstaller, aucun binaire compilé, aucune modification de `install.py`.

Notes publiées : `doc/RELEASE_NOTES_0.9.1.md`.
Pour la recette embarquée (bundle 42 Mo, AppImage, ZIP Windows), voir
`doc/RELEASE_LINUX_FR.md` et `release_qt6.sh`.

## 0. Prérequis

- `dpkg-deb` (paquet `dpkg`), `git`, et `gh` pour publier : `sudo apt-get install -y dpkg git gh`.
- **Aucun root n'est nécessaire** pour construire ni pour relire le paquet.
- **PyQt6 n'est pas nécessaire sur la machine de construction** : la recette
  saute le contrôle de dépendances d'`install.py` (`-x`) et déclare la
  dépendance réelle dans `DEBIAN/control`.
- Un bureau (X11/Wayland) est nécessaire **seulement** pour la recette
  graphique finale.

## 1. Version et notes

Déjà appliqué ici en 0.9.1 (commit de préparation de release) :

```bash
cd /chemin/vers/ConvertAll-py
sed -i "s/^__version__ = '0\.9\.0'$/__version__ = '0.9.1'/" source/convertall.py
sed -i 's/0\.9\.0/0.9.1/g' win/convertall-all.iss win/convertall-user.iss
# bannière + ligne « Version » des manuels, sans réécrire les journaux historiques :
for f in doc/README.html doc/README_fr.html doc/README_de.html doc/README_es.html \
         doc/README_ru.html docs/README.html; do
  sed -i '0,/Python\/Qt6 fork 0\.9\.0/s//Python\/Qt6 fork 0.9.1/' "$f"
  sed -i '0,/Version 0\.9\.0/s//Version 0.9.1/; 0,/Versión 0\.9\.0/s//Versión 0.9.1/; 0,/Версия 0\.9\.0/s//Версия 0.9.1/' "$f"
done
# attentes de tests (tests/test_cli.py, tests/test_gui.py, tests/test_packaging.py,
# tests/test_release_tools.py) : voir le commit de préparation de release.
```

`tests/test_packaging.py::test_versions_are_consistent_without_rewriting_history`
impose que `source/convertall.py`, `win/*.iss` et le **premier** numéro de
version de chaque `README*.html` soient identiques : sautez une de ces étapes et
la porte QA échoue.

## 2. Construire le `.deb`

À lancer **à la racine du dépôt**. Le bloc est complet et idempotent :

```bash
set -euo pipefail
cd /chemin/vers/ConvertAll-py

VERSION=$(sed -n "s/^__version__ = '\([^']*\)'.*/\1/p" source/convertall.py | head -1)
REV=1
ARCH=all                                  # code Python pur : toutes les architectures
PKG=convertall
MAINTAINER="$(git config user.name) <$(git config user.email)>"   # champ public
STAGE="build/deb/${PKG}_${VERSION}-${REV}_${ARCH}"

rm -rf "$STAGE" && mkdir -p "$STAGE"

# 1) L'application seule, installée dans un DESTDIR Debian, sans root.
#    -x  : saute le contrôle de dépendances (PyQt6 absent du python3 de build)
#    -p /usr : les chemins définitifs (/usr/bin/convertall, /usr/share/convertall…)
#    -b  : écrit sous $STAGE ; ce chemin n'apparaît jamais dans le lanceur.
#    IMPORTANT : /usr/bin/python3, pas un venv — install.py inscrit
#    sys.executable dans /usr/bin/convertall.
/usr/bin/python3 install.py -x -p /usr -b "$PWD/$STAGE"

# 2) Métadonnées Debian.
mkdir -p "$STAGE/DEBIAN"
SIZE=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION-$REV
Architecture: $ARCH
Maintainer: $MAINTAINER
Section: science
Priority: optional
Installed-Size: $SIZE
Depends: python3 (>= 3.11), python3-pyqt6 (>= 6.4)
Recommends: qt6-translations-l10n, fonts-dejavu-core
Homepage: https://github.com/jojo8356/ConvertAll-py
Description: flexible unit converter (Python/PyQt6 edition)
 ConvertAll can combine arbitrary units, with decimal or fractional
 output, history, favourites and seven unit catalogues.
 .
 Python, PyQt6 and the Qt6 runtime are taken from the Debian/Ubuntu
 archives: this package embeds no interpreter and no Qt library.
EOF

cat > "$STAGE/usr/share/doc/convertall/copyright" <<'EOF'
ConvertAll is distributed under the GNU General Public License,
version 2 or (at your option) any later version; see LICENSE.

This Debian package only ships the Python source of ConvertAll.
Python 3 and PyQt6 are installed separately from the distribution
archives; PyQt6 is GPLv3 or commercially licensed, not LGPL.
See LICENSE-GPL-3.0 and LICENCES_QT6_FR.md in this directory.
Repackaged by the jojo8356/ConvertAll-py fork; upstream author:
Doug Bell.
EOF

{
  echo "convertall ($VERSION-$REV) unstable; urgency=medium"
  echo
  echo "  * Light Debian package: Python 3 and PyQt6 are dependencies from"
  echo "    the distribution archives instead of an embedded runtime."
  echo
  echo " -- $MAINTAINER  $(date -R)"
} | gzip -9n > "$STAGE/usr/share/doc/convertall/changelog.Debian.gz"

# 3) Scripts de maintenance : menu, cache d'icônes, .pyc du python3 cible.
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v py3compile >/dev/null 2>&1; then py3compile -p convertall || true; fi
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

# 4) Construction (--root-owner-group : root:root même sans être root).
mkdir -p dist
DEB="dist/${PKG}_${VERSION}-${REV}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB"
dpkg-deb --info "$DEB"
```

## 3. Contrôles avant installation

```bash
DEB=dist/convertall_0.9.1-1_all.deb

dpkg-deb --info     "$DEB" | head -20          # Depends, Architecture: all, taille
dpkg-deb --contents "$DEB" | grep -E 'usr/bin|applications|hicolor|data/units.dat'

rm -rf build/deb-extract build/deb-smoke
dpkg-deb --extract "$DEB" build/deb-extract
test -x build/deb-extract/usr/bin/convertall
grep -q "exec /usr/bin/python3 /usr/share/convertall/convertall.py" \
        build/deb-extract/usr/bin/convertall
grep -q "dataFilePath = '/usr/share/convertall/data'" \
        build/deb-extract/usr/share/convertall/convertall.py

# Recette « relocalisée » : lancer l'application avant de l'installer.
# Le lanceur du paquet est volontairement absolu (/usr/...), on réécrit donc
# les trois chemins dans une copie jetable.
cp -a build/deb-extract build/deb-smoke
P=$PWD/build/deb-smoke
sed -i "s#'/usr/share/convertall/data'#'$P/usr/share/convertall/data'#;
        s#'/usr/share/doc/convertall'#'$P/usr/share/doc/convertall'#;
        s#'/usr/share/icons/convertall'#'$P/usr/share/icons/convertall'#" \
       "$P/usr/share/convertall/convertall.py"
export QT_QPA_PLATFORM=offscreen
python3 "$P/usr/share/convertall/convertall.py" --version     # ConvertAll 0.9.1 (Qt6)
python3 "$P/usr/share/convertall/convertall.py" -q 1 in cm    # 1 in = 2.54 cm
python3 "$P/usr/share/convertall/convertall.py" --test-all    # 7 × All units pass tests

lintian "$DEB"      # facultatif : avertissements de politique Debian
```

`python3` doit ici être l'interpréteur qui a accès à `python3-pyqt6`.

## 4. Installer et accepter

```bash
sudo apt-get install -y python3-pyqt6        # ou : sudo apt-get -f install
sudo dpkg -i dist/convertall_0.9.1-1_all.deb

convertall --version
convertall -q 1 in cm
convertall --test-all
QT_QPA_PLATFORM=offscreen convertall --gui-smoke-test   # widgets sans écran
convertall                                              # fenêtre réelle, menu, icône
dpkg -L convertall | head

# Retrait propre
sudo dpkg -r convertall
```

## 5. Taguer et publier

```bash
git add -A && git commit -m "Release 0.9.1: light Debian package"
git tag -a v0.9.1 -m "ConvertAll 0.9.1 (Qt6, paquet Debian léger)"
git push origin HEAD:arena/f556546b-convertall-py     # ou votre branche de release
git push origin v0.9.1

gh release create v0.9.1 --verify-tag --draft \
  --title "ConvertAll 0.9.1 — Qt6 (paquet Debian léger)" \
  --notes-file doc/RELEASE_NOTES_0.9.1.md \
  dist/convertall_0.9.1-1_all.deb

gh release view v0.9.1
# publication définitive, si le brouillon est bon :
# gh release edit v0.9.1 --draft=false --latest
```

`--verify-tag` refuse de créer la release si `v0.9.1` n'existe pas ou ne pointe
pas sur le SHA poussé ; ne déplacez jamais un tag déjà publié.

## Annexe A — Règle « dépôt ou embarqué »

Vérifier une dépendance sur la **distribution cible** :

```bash
apt-cache policy python3 python3-pyqt6     # présent ? quelle version ?
apt-cache show python3-pyqt6 | grep -E '^(Version|Depends|Recommends)'
```

Ordres de grandeur observés : Debian 12 « bookworm » → PyQt6 6.4.2,
Debian 13 « trixie » → 6.9.0, Debian forky/sid → 6.11.x.

- Dépendance présente dans les dépôts → `Depends:` (ou `Recommends:`),
  rien dans le paquet. C'est le cas de **tout** ConvertAll ici.
- Dépendance absente ou trop ancienne pour la cible → deux issues :
  1. relever le plancher (`python3-pyqt6 (>= 6.11)`) et n'annoncer que les
     distributions qui le fournissent ;
  2. n'embarquer que le manquant sous `/usr/lib/convertall` (roue PyQt6 +
     `PyQt6-Qt6`) et garder `Depends: python3` : c'est le compromis de la
     release 0.9.0, qui embarque tout.
- Contrôle statique effectué : toutes les classes, énumérations `Qt.*`,
  `sip.*` et `QLibraryInfo` utilisées par `source/` existent dès les stubs
  PyQt6 6.4.2, donc `python3-pyqt6 (>= 6.4)` est un plancher défendable.

## Annexe B — État des vérifications

Vérifié pour la 0.9.1 :

- construction complète de `convertall_0.9.1-1_all.deb` (243 976 octets) ;
- `dpkg-deb --info` : `Architecture: all`,
  `Depends: python3 (>= 3.11), python3-pyqt6 (>= 6.4)`, `postinst` présent ;
- `dpkg-deb --extract` : lanceur `/usr/bin/convertall`, chemins `dataFilePath`,
  `helpFilePath`, `iconPath` figés sur `/usr`, données, traductions, manuel,
  entrée de menu et icône présents ;
- recette relocalisée : `--version`, `-q 1 in cm`, `--runtime-info`,
  `--test-all` (7 catalogues) réussis ;
- suite du dépôt hors interface : 4 414 tests réussis, seuls les tests
  exigeant QtGui/QtWidgets échouent dans l'environnement de construction
  (aucune bibliothèque `libGL`/X11 disponible).
- contrôle statique de compatibilité PyQt6 6.4.2 (annexe A).

Reste à faire sur une machine bureau :

- `bash test_all_qt6.sh --no-build` avec l'arbre propre, avant de taguer ;
- `sudo dpkg -i` puis `convertall`, `--gui-smoke-test` et retrait `dpkg -r` ;
- validation réelle avec la version distribuée de PyQt6 (6.4/6.9) si vous
  annoncez ces distributions.
