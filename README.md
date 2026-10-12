# ConvertAll-py — Qt6 0.9.1

ConvertAll permet de combiner librement les unités : pouces par décennie,
mètres-livres, milles nautiques au cube… Ce dépôt maintient l'application
**Python / PyQt6**, distincte de l'application Flutter actuelle de l'amont.

**État : 0.9.1 candidate, `.deb` natif léger à revalider.** Le tag Qt6
`v0.9.0` reste au SHA `a3b93db` ; ses résultats ne valident pas ce nouveau
commit. La CI ajoute Debian Bookworm/Trixie avec Qt/PyQt6 fournis par APT,
sans remplacer les huit jobs du profil épinglé et les deux bundles.
Aucune certification bureau réel/DPI/GPU n'est revendiquée. Qt5 0.8.1 reste
immuable au commit `b10b8e7837e30a2ec9a957a9a2519e4ac0334db3`.

## Lancer les sources

Profil : **Python 3.11–3.14, PyQt6 6.11.0 / Qt 6.11.2 / PyQt6-sip 13.13.0**.
Utiliser un environnement dédié ; ne pas installer PyQt5/PySide avec PyQt6.

```bash
python3.11 -m venv .venv/qt6
. .venv/qt6/bin/activate
python -m pip install -r requirements-qt6.txt
python source/convertall.py
python source/convertall.py -q 1 in cm
```

Windows PowerShell : `py -3.11 -m venv .venv/qt6`, puis
`.venv\qt6\Scripts\Activate.ps1`. La cible binaire Windows est x64,
Windows 10 1809 ou ultérieur / Windows 11. Linux nécessite les bibliothèques
système Qt habituelles, même pour les tests offscreen. La CI cible Ubuntu 24.04
et Windows Server 2022 ; macOS, Inno Setup, DPI/GPU et bureau réel restent
à vérifier manuellement.

## Un seul lancement pour les tests et le bundle

À exécuter vous-même depuis la racine du dépôt (Git Bash sous Windows) :

```bash
bash test_all_qt6.sh
```

Le lanceur prépare `.venv/test-all-qt6`, installe les profils épinglés,
exécute la suite complète et la couverture, puis construit/teste le vrai bundle
PyInstaller uniquement si la suite source passe. Il produit :

- `build/qt6-diagnostics/<run>/SUMMARY.txt` : résumé à transmettre ;
- `build/qt6-diagnostics/qt6-results-<run>.tar.gz` : rapports et logs uniquement ;
- `build/qt6-native/<run>/dist/convertall/` : bundle conservé séparément.

Premier passage plus rapide : `bash test_all_qt6.sh --no-build`.
Réutilisation sans installation :
`bash test_all_qt6.sh --no-install --python .venv/test-all-qt6/bin/python`.
Sous Windows, remplacer le chemin par `.venv/test-all-qt6/Scripts/python.exe`.
Aucun sudo, commit, push, tag ni release n'est effectué par ce lanceur.

La suite conserve les assertions sur les **7 catalogues / 4104 définitions**,
les références numériques, aller-retours, fractions/bases, CLI en sous-processus,
vrais widgets/signaux/clavier/dialogues Qt6, traductions, préférences compatibles
Qt5, installateur Unix isolé et archives source reproductibles. Le seuil reste
**80 % de couverture combinée instructions/branches**, sous-processus inclus.
La CI teste les quatre versions Python 3.11 à 3.14 sur Linux et Windows et
construit les deux bundles seulement après réussite de tous les tests.

**La CI ne se déclenche que pour un commit marqué.** Le workflow Qt6 est
conditionné à la présence de `[PROD]` dans le message de commit (titre ou
branche pour une pull request) ; les commits ordinaires ne lancent donc aucun
job et ne consomment pas de minutes. Pour valider un SHA :

```bash
git commit -m "[PROD] Prepare the 0.9.1 release"
git push origin arena/0adacf84-convertall-py
```

`release_qt6.sh --wait-ci --draft` exige un run **push** marqué et vert sur les
12 jobs de ce SHA exact : un push silencieux, un run en échec ou un lancement
manuel (« Run workflow », utile pour un contrôle ponctuel) ne suffisent pas.
Ne jamais mettre ce marqueur dans un commit de routine.

Commit déjà poussé sans le marqueur ? Inutile de réécrire l'historique : un
commit vide marqué suffit, et c'est ce nouveau SHA (arbre identique) qu'il
faudra release.

```bash
git commit --allow-empty -m "[PROD] Validate this tree for the release"
git push origin arena/0adacf84-convertall-py
```

## Release avec exécutables, `.deb` et `.AppImage`

Sur Linux x86_64 Debian/Ubuntu, avec le venv de QA et les outils système prêts :

```bash
bash release_qt6.sh --wait-ci --draft
```

Le script impose la CI du SHA actuel, reteste les sources, construit/contrôle
portable et AppImage autonomes, puis un **`.deb` contenant seulement les sources
et ressources**. Ce dernier déclare Python/PyQt6/Qt via `Depends` APT (minimum
Python 3.11, PyQt6/Qt 6.4.2), sans runtime embarqué ; il est contrôlé avec
`/usr/bin/python3` hors du venv de build. Les `.exe` Windows complets et sources
viennent de la même CI. Le profil autonome 6.11 reste inchangé.
Il crée un **brouillon 0.9.1 non publié**, jamais Latest ; `v0.9.0` n'est pas
modifié. Sans `--draft`, seuls les assets locaux sont préparés. Aucun
pip/sudo/apt n'est exécuté par ce script.

Un run interrompu après l'étape 3 (AppImage, artefacts CI, provenance, draft)
se reprend **sans reconstruire** les trois premières étapes :

```bash
bash release_qt6.sh --resume --wait-ci --draft                  # dernier run
bash release_qt6.sh --resume 20261012T065426Z-418571 --draft    # run précis
```

Rien n'est repris sur parole : le rapport du bundle est re-haché fichier par
fichier, l'archive portable est réextraite et relancée, le SHA-256 du `.deb`
recontrôlé, et le bundle doit être lié au *même* SHA et au *même* run CI.
Reprendre les artefacts d'un autre commit est refusé : ils seraient périmés,
il faut alors relancer sans `--resume`.
Voir [la procédure complète et les limites](doc/RELEASE_LINUX_FR.md).

## Diagnostics et publication

```bash
python source/convertall.py --version
python source/convertall.py --runtime-info
python source/convertall.py --test-all
QT_QPA_PLATFORM=offscreen python source/convertall.py --gui-smoke-test
```

- [Portage et compatibilité Qt6](doc/PORTAGE_QT6_FR.md)
- [Validation et commandes de release Qt6](doc/RELEASE_QT6_FR.md)
- [Notes 0.9.1, paquet Debian léger à valider](doc/RELEASE_NOTES_0.9.1.md)
- [Historique Qt6 0.9.0](doc/RELEASE_NOTES_0.9.0.md)
- [Licences et redistribution](doc/LICENCES_QT6_FR.md)
- [Audit/benchmark **historique 0.8.0**](doc/MIGRATION_QT6_FR.md)
- [Procédure **historique Qt5 0.8.1**](doc/RELEASE_QT5_FR.md)

Le workflow Qt5 est manuel et extrait son SHA historique : il ne teste jamais
ces sources Qt6 avec PyQt5. `test_all_qt5.sh` refuse ce nouvel arbre ; utiliser
l'archive du commit Qt5 pour reproduire ses tests. Ne pas retargeter `v0.8.1`.
La CI ne publie rien automatiquement. Offscreen n'est pas une certification
d'un bureau réel et le benchmark 0.8.0 n'est pas une mesure de cette 0.9.1.
