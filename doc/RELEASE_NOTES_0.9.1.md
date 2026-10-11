# ConvertAll 0.9.1 — Qt6, paquet Debian léger

Version 0.9.1 du fork PyQt6 : **aucun changement de fonctionnalités** par
rapport à la 0.9.0, seule la distribution Debian/Ubuntu change.

## Empaquetage

- `convertall_0.9.1-1_all.deb` : paquet Debian **léger** (~240 Ko) qui
  n'embarque ni interpréteur Python ni bibliothèque Qt.
  - `Depends: python3 (>= 3.11), python3-pyqt6 (>= 6.4)`
  - `Recommends: qt6-translations-l10n, fonts-dejavu-core`
  - `Architecture: all` (code Python pur, toutes architectures)
- Installation : `/usr/bin/convertall`, `/usr/share/convertall`,
  `/usr/share/doc/convertall`, entrée de menu et icône hicolor.

## Compatibilité

- PyQt6 `>= 6.4` : Debian 12 « bookworm » (6.4.2), Debian 13 « trixie »
  (6.9.0), Ubuntu 24.04 et suivants.
- Toutes les classes, énumérations `Qt.*`, `sip.*` et `QLibraryInfo` utilisées
  par l'application existent déjà dans les stubs PyQt6 6.4.2.
- La QA du dépôt valide PyQt6 6.11.0 / Qt 6.11.2 ; le rendu graphique avec la
  version distribuée doit être confirmé sur un bureau réel après installation.

## Contrôles effectués sur le paquet

- Construction : `install.py -x -p /usr -b <DESTDIR>` puis `dpkg-deb --build`.
- Depuis l'arborescence installée : `--version`, `-q 1 in cm`,
  `--runtime-info` et `--test-all` (7 catalogues) réussis.
- Interface graphique : à valider après `dpkg -i`
  (`QT_QPA_PLATFORM=offscreen convertall --gui-smoke-test`, puis lancement réel).

## Limites

- Le bundle autonome 42 Mo, l'AppImage et le ZIP Windows de la 0.9.0 ne font
  pas partie de cette release ; joignez-les seulement après leur validation.
- La syntaxe de cette release reste 0.9.1 dans `source/convertall.py`,
  `win/*.iss` et les manuels.
