# Release Qt6 0.9.1 : `.deb` léger et bundles autonomes

À exécuter par l'utilisateur, pas par l'agent. `v0.9.0` reste au SHA
`a3b93db8aed87787c531c6067c43199e4d48159a` : aucun tag/asset publié n'est
retargeté ou remplacé automatiquement. Les nouvelles recettes et la version
0.9.1 attendent la validation de leur nouveau SHA.

## 1. Deux profils distincts

| Asset | Contenu/runtime |
| --- | --- |
| `convertall_0.9.1-1_all.deb` | Seulement code Python + ressources ; Python/PyQt6/Qt/SIP fournis par APT |
| `ConvertAll-0.9.1-qt6-linux-x86_64.tar.gz` | Exécutable et dossier complet autonome |
| `ConvertAll-0.9.1-x86_64.AppImage` | AppImage autonome en un fichier |
| `ConvertAll-0.9.1-qt6-windows-x86_64.zip` | Deux `.exe` et dossier complet de la même CI Windows |
| Archive source, `SHA256SUMS`, rapports | SHA/run, octets, versions réellement chargées et checksums |

Le `.deb` ne contient **aucun ELF, `.so`, PyQt6, libpython, Qt, roue,
.dist-info, bytecode ou environnement virtuel**. Il conserve les sept
catalogues, six QM applicatifs, PNG nécessaires, SVG du menu, aides et licences.
Les TS/scripts de build restent dans l'archive source, pas dans le paquet installé.
La charge utile est compressée en xz niveau 9 par dpkg-deb.

Le lanceur `/usr/bin/convertall` utilise **`/usr/bin/python3 -E -s`** ; il ne
cherche pas le Python du venv dans PATH. Les modules applicatifs sont sous
`/usr/share/convertall`, les aides sous `/usr/share/doc/convertall`.
`Architecture: all` décrit un paquet sans binaire spécifique à une architecture,
pas une certification bureau/GPU de toutes les machines.

Dépendances déclarées dans `Depends` :

- `python3 (>= 3.11)` ;
- `python3-pyqt6 (>= 6.4.2)` ;
- `python3-pyqt6.sip (>= 13.4.1)` ;
- `qt6-translations-l10n (>= 6.4.2)`.

APT résout les bibliothèques Qt/desktop transitives. Elles sont partagées avec
les autres applications, pas copiées dans le `.deb`. **Un fichier plus petit
ne supprime pas leur coût sur une machine qui ne les a pas encore.** Aucun
gain chiffré n'est annoncé avant mesure réelle.

Les bundles/AppImage gardent le profil épinglé PyQt6 6.11.0 / Qt 6.11.2 /
PyQt6-sip 13.13.0. L'installation source avec `install.py` garde son profil
historique épinglé ; le `.deb` dispose de son propre lanceur/QA natifs.

## 2. Préparer les dépendances (vous-même, si absentes)

```bash
sudo apt-get update
sudo apt-get install -y dpkg binutils squashfs-tools desktop-file-utils gh python3-pyqt6 python3-pyqt6.sip qt6-translations-l10n
```

Le venv `.venv/test-all-qt6` reste nécessaire pour les tests/bundles épinglés.
Le script n'exécute aucun apt, pip ou sudo. Les contrôles natifs refusent un
PyQt6 provenant d'un venv ou de `/usr/local`, même s'il a la bonne version.
Le champ Debian Maintainer est public et vient de l'identité Git locale ;
utiliser `--maintainer 'Nom <adresse>'` pour choisir une autre identité.

## 3. Construire et créer le draft 0.9.1

```bash
set -euo pipefail
git pull --ff-only origin arena/0adacf84-convertall-py
bash release_qt6.sh --wait-ci --draft
```

Le lanceur exige la CI du SHA actuel : huit tests Ubuntu/Windows × Python
3.11–3.14, deux bundles et deux jobs **Debian native Qt / bookworm et trixie**.
Ces derniers utilisent Qt/PyQt6/SIP APT, un venv de tests avec
`--system-site-packages` et seulement les dépendances pytest (aucune roue Qt).
Ils exécutent les régressions moteur/GUI/CLI/traductions/préférences, avec le
seuil de couverture 80 % inchangé, puis construisent et contrôlent le `.deb`
avec `/usr/bin/python3` hors de ce venv. Les assertions du profil frozen restent
exécutées intégralement par les huit jobs épinglés.

Les contrôles de traductions natives sont exacts mais non naïfs : Debian ne
fournit pas forcément toutes les langues de widgets (`qtbase_sv` peut manquer).
Un catalogue présent doit charger ; un catalogue réellement absent doit être
signalé par l'application (`Warning: translation file ... could not be loaded`)
sans exception. Les six `convertall_*.qm` applicatifs restent obligatoires,
et leur absence échoue toujours. Les bundles conservent, eux, les six langues
de widgets du profil épinglé.

Localement le lanceur refait la suite épinglée et les bundles. Le `.deb` est
construit depuis les **sources**, jamais en supprimant des `.so` d'un exécutable
PyInstaller. Après extraction sans installation/root : comparaison des octets,
absence de runtime embarqué, quatre conversions, sept catalogues, traductions
applicatives/qtbase système et GUI offscreen. Le rapport
`native-deb-validation.json` donne taille, dépendances et origine Python/Qt.

Les contrôles portable/AppImage/Windows restent inchangés. Le minimum GLIBC
mesuré depuis leurs ELF concerne **portable/AppImage**, pas le paquet Python
Debian : les paquets système gèrent leur propre ABI et leurs dépendances.

Assets : `dist/qt6-release/<SHA>-<run>/`. Logs/staging : `build/qt6-release/<run>/`.
Sans `--draft`, seuls les assets sont préparés. Avec ce flag : tag `v0.9.1`
au SHA testé puis brouillon non publié. Aucun retarget/clobber/force/Latest.

Pour préparer seulement le `.deb`, sans bundles ni publication :

```bash
/usr/bin/python3 -E -s tools/build_deb.py \
  --output-dir dist/debian \
  --maintainer "$(git config user.name) <$(git config user.email)>"
```

Cette commande contrôle le paquet natif ; elle ne remplace ni la suite complète
ni la CI du même SHA avant publication. Pas d'overwrite d'un paquet existant.

## 4. Contrôles CI et diagnostic des échecs

La CI Qt6 doit être verte sur **12 jobs** pour le SHA exact avant tout tag. Les
jobs `Debian native Qt / bookworm|trixie` valident le `.deb` léger avec le
Python et le Qt d'APT, hors venv de test ; la vérification du runtime système
est une étape séparée du build, donc le statut des étapes situe déjà la panne.

`tools/build_deb.py` publie ses jalons en annotations (`notice`) et, en cas
d'échec, une annotation `error` avec l'étape fautive, le message et les
dernières lignes de trace ; le même texte est écrit dans
`build/native-debian/native-deb-failure.txt` (artefact `qt6-native-deb-<suite>`).
Ainsi `gh api .../check-runs/<id>/annotations` suffit à diagnostiquer un échec
même quand les logs et artefacts ne sont pas téléchargeables.

## 5. AppImage verrouillée

`tools/appimage-lock.json` conserve IDs et SHA-256 du builder et du runtime.
Le builder utilise explicitement le runtime épinglé et **zstd**, seul
compresseur de son mksquashfs embarqué. Aucun téléchargement « latest » ni
fallback non vérifié. Le correctif zstd a permis le draft 0.9.0 utilisateur ;
ce n'est pas une certification du nouveau SHA 0.9.1.

Le runtime [type2-runtime](https://github.com/AppImage/type2-runtime) choisi
est statique (musl/libfuse) ; la QA emploie extraction/exécution sans FUSE.
Le montage FUSE réel et la compatibilité GPU restent à accepter sur le poste.

L'auto-extraction lit `/proc/self/exe` à l'offset calculé depuis la table des
sections ELF : certains montages (dossiers synchronisés ou nuagiques, clone
rangé dans « Téléchargements ») renvoient alors d'autres octets et l'extraction
échoue en « Failed to open squashfs image ». Dans ce cas le script affiche un
`WARNING` puis retente, sans jamais changer de binaire : copie vérifiée sur
disque local (`TMPDIR`, puis `/dev/shm`), puis runtime épinglé via
`TARGET_APPIMAGE` (lecture par chemin), puis lecture directe du payload avec
`unsquashfs` (`squashfs-tools` est déjà requis). Le repli n'est pas un
contournement : seuls les octets décrits par les pins sont exécutés, et un
échec total affiche la taille, le SHA-256 relu et le pin attendu. Si les
`WARNING` persistent, déplacer le clone sur un disque local.

## 6. Installer et publier séparément

Dans une VM Debian/Ubuntu dédiée, après checksums :

```bash
sudo apt install ./convertall_0.9.1-1_all.deb
convertall
```

APT installe automatiquement les dépendances manquantes. `dpkg -i` seul ne les
résout pas. Tester menu, clavier, réouverture/historique/fontes/langues, upgrade
puis désinstallation ; sauvegarder les préférences avant migration volontaire.
Tester aussi AppImage/portable en bureau réel et ZIP extrait sur Windows.
Le script ne réalise pas cette installation et ne modifie pas votre vrai HOME.

Revoir les licences/sources correspondantes des bundles et compléter le texte
du draft avec les résultats observés. Ne pas modifier l'arbre testé : sinon
nouveau SHA/nouvelle QA. Seulement après acceptation :

```bash
gh release view v0.9.1 --repo jojo8356/ConvertAll-py
gh release edit v0.9.1 --repo jojo8356/ConvertAll-py --draft=false --prerelease=false --latest
```

`v0.9.0` et la baseline Qt5 `v0.8.1` restent immuables. Aucun gain de performance,
certification installateur/desktop/macOS ni inventaire juridique complet n'est
revendiqué par la QA offscreen.
