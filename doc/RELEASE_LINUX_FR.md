# Release Qt6 : exécutables, Debian et AppImage

Le lanceur **`release_qt6.sh` est à exécuter par l'utilisateur**, sur Linux
x86_64 Debian/Ubuntu. L'agent n'exécute pas ces nouvelles recettes. La QA
4575 PASS / 90,70 % et la CI verte du SHA `a72ee1d` valident les anciens
sources/bundles, pas encore ces nouveaux paquets ni le nouveau commit.

## 1. Ce que le script prépare

Pour la version 0.9.0 :

| Asset | Contenu |
| --- | --- |
| `ConvertAll-0.9.0-qt6-linux-x86_64.tar.gz` | Exécutable Linux + toutes ses bibliothèques et ressources |
| `convertall_0.9.0-1_amd64.deb` | Application privée sous `/usr/lib/convertall`, commande `/usr/bin/convertall`, menu et icône |
| `ConvertAll-0.9.0-x86_64.AppImage` | AppImage type 2, `AppRun`, icône, traductions et runtime Qt/Python |
| `ConvertAll-0.9.0-qt6-windows-x86_64.zip` | **Les deux `.exe` et leur dossier complet**, téléchargés depuis la CI Windows du même SHA |
| `ConvertAll-0.9.0-qt6-source.tar.gz` | Archive source exacte téléchargée depuis la CI, avec checksum et provenance |
| `SHA256SUMS`, JSON/XML et `RELEASE_NOTES.md` | Checksums, rapports, SHA/run, baseline GLIBC et chiffres réellement observés |

Le build est **onedir** : publier seulement `convertall` ou `convertall.exe`
les rendrait inutilisables sans leurs ressources/Qt/Python. L'AppImage, elle,
est un fichier exécutable unique. Le ZIP Windows n'est **pas** un installateur
Inno : aucun `.exe` installateur non testé n'est inventé. Pas de build macOS.

## 2. Préparer les outils (une fois, seulement si absents)

Le venv `.venv/test-all-qt6` déjà utilisé par le lanceur de QA suffit. Le script
ne lance **aucun pip, sudo ou apt**. Installer vous-même les utilitaires manquants :

```bash
sudo apt-get update
sudo apt-get install -y dpkg binutils squashfs-tools desktop-file-utils gh
```

Les bibliothèques système Qt sont celles du guide `RELEASE_QT6_FR.md`, déjà
nécessaires pour la QA. Prévoir plusieurs Go libres pour les copies/extractions.
GitHub CLI doit être authentifié avec accès au dépôt ; vérifier sur votre
machine avec `gh auth status`. Aucun credential n'est demandé dans le chat.

Le champ Debian **Maintainer est public**. Par défaut il vient de
`git config user.name` / `git config user.email`, sans modifier cette config.
Pour choisir une autre identité, ajouter `--maintainer 'Nom <adresse>'`.

## 3. Une commande : tout préparer puis créer le draft

Depuis le clone, sur la branche de session :

```bash
set -euo pipefail
git pull --ff-only origin arena/0adacf84-convertall-py
bash release_qt6.sh --wait-ci --draft
```

`--wait-ci` attend le run push du **SHA actuel**, puis impose les huit tests
Ubuntu/Windows × Python 3.11–3.14 et les deux bundles verts. Aucun ancien run
Qt5/Qt6 d'un autre SHA ne convient. La sélection utilise l'API GitHub : pas
besoin des nouveaux flags `gh run list --commit/--status` absents de vieux gh.
`--run-id NUMÉRO` est possible, mais le même contrôle de SHA s'applique.

Le script relance ensuite la QA locale complète, construit le bundle Linux
sur **votre machine** avec le profil épinglé et le contrôle. Il ne réutilise
pas le bundle Ubuntu 24.04 pour faire croire à une compatibilité Debian :
il calcule le minimum GLIBC depuis les symboles ELF et l'inscrit dans
`Depends` du `.deb` ainsi que dans la provenance/les notes.

Il produit et contrôle effectivement :

- archive Linux extraite : CLI, runtime, 7 catalogues et widgets offscreen ;
- `.deb` extrait **sans installation et sans root** : lanceur relocalisable,
  runtime, conversions, catalogues et widgets ; desktop entry validée ;
- véritable AppImage via `--appimage-extract-and-run`, puis son `AppRun`
  extrait : les mêmes contrôles sans exiger FUSE pendant la QA ;
- ZIP Windows complet : octets vérifiés contre le rapport CI, liste et CRC du ZIP ;
- archive source CI : version, SHA, checksum et provenance vérifiés.

Les contrôles arrêtent le script au premier échec. Les logs/staging restent
sous `build/qt6-release/<run>/`; les assets prêts sous
`dist/qt6-release/<SHA>-<run>/`. Aucun gros artefact n'est ajouté à Git.

**Sans `--draft`**, il prépare exactement les mêmes assets mais ne crée ni
tag ni release. Avec `--draft`, après tous les contrôles, il crée le tag
`v0.9.0` au SHA testé s'il manque, puis un **brouillon non publié**.
Il refuse un tag pointant ailleurs ou une release préexistante : aucun
retarget, `--force`, `--clobber`, commit, push ou publication Latest.

Pour un Python personnalisé déjà préparé :

```bash
CONVERTALL_RELEASE_PYTHON=/chemin/venv/bin/python bash release_qt6.sh --wait-ci --draft
```

## 4. Outils AppImage verrouillés

`tools/appimage-lock.json` fixe **l'ID d'asset et son SHA-256** pour le builder
AppImage et pour le runtime embarqué. Les empreintes viennent des champs
`digest` de l'API GitHub, consultés le 10 octobre 2026. Une vérification SHA
précède toute exécution d'un outil téléchargé. Le builder reçoit explicitement
`--runtime-file` : il ne télécharge pas silencieusement un nouveau runtime.

Les upstreams utilisent un tag flottant `continuous`. Si l'asset épinglé est
supprimé, le script échoue : ne pas désactiver le contrôle ni télécharger
« latest » au hasard. Mettre à jour les IDs/empreintes délibérément dans un
nouveau commit, puis refaire la QA. Le hash n'est pas une attestation juridique
ou une vérification indépendante de l'auteur du binaire.

Références : [appimagetool](https://github.com/AppImage/appimagetool) et
[type2-runtime](https://github.com/AppImage/type2-runtime). Le runtime choisi
est statique (musl/libfuse) ; il ne réclame pas libfuse2. Le montage réel FUSE
reste à accepter sur le poste cible ; l'extraction est une solution de secours.

## 5. Acceptation réelle puis publication séparée

Avant de publier les binaires :

1. Depuis le dossier d'assets affiché, `sha256sum -c SHA256SUMS`.
2. Lancer l'archive portable et l'AppImage en **bureau réel**, pas offscreen :
   clavier, aide, traductions, fontes, historique, réouverture, DPI/écrans.
3. Dans une **VM Debian/Ubuntu dédiée**, installer le `.deb` avec apt, lancer
   via le menu et la commande, tester upgrade puis désinstallation. Le script
   ne touche pas à votre installation Qt5 ni à votre vrai HOME. Sauvegarder
   les préférences avant de tester volontairement leur migration.
4. Extraire tout le ZIP sur Windows et accepter son lancement réel.
5. Revoir licences/notices **et sources correspondantes des dépendances**.
   Les notices des roues disponibles sont copiées dans `doc/third-party`,
   mais ceci n'est pas un inventaire juridique complet des bibliothèques
   système/Qt/Python/AppImage. L'archive source de l'application seule ne
   dispense pas des autres obligations. Voir `LICENCES_QT6_FR.md`.
6. Compléter le **texte du draft** avec l'acceptation observée, sans modifier
   l'arbre source déjà testé. Si le code/config change, nouveau SHA et nouvelle QA.

Seulement après cette revue, publier volontairement :

```bash
gh release view v0.9.0 --repo jojo8356/ConvertAll-py
gh release edit v0.9.0 --repo jojo8356/ConvertAll-py --draft=false --prerelease=false --latest
```

Ne pas lancer ce dernier bloc par défaut. Qt5 `v0.8.1` reste immuable ; il
reste Latest tant que la publication Qt6 n'a pas été explicitement acceptée.
