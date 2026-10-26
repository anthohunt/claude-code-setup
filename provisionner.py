#!/usr/bin/env python3
"""Provisionnement des comptes Claude Code d'un ordinateur.

Pour CHAQUE dossier de configuration Claude de l'ordinateur (~/.claude* qui contient
.credentials.json, settings.json ou projects/), garantit :
  - skills    -> le dossier de skills partage (lien ; jonction sous Windows) ;
  - CLAUDE.md -> le CLAUDE.md global (lien, ou copie tenue a jour quand l'OS refuse le lien) ;
                 une modification faite dans le compte remonte dans le global, jamais perdue ;
  - settings.json : CLAUDE_CODE_PLUGIN_DIRS = tous les mods du dossier des mods, et
                 (facultatif) autoMemoryDirectory, plafond de la liste des skills (fusion JSON,
                 les autres reglages ne bougent pas, sauvegarde avant la premiere modification) ;
et, facultativement, ~/.claude-machine.md -> la partie propre a la machine, que le CLAUDE.md global
importe (@~/.claude-machine.md).

Tout se regle dans un fichier de configuration JSON (voir provisionner.exemple.json) :
  --config FICHIER, ou $PROVISION_CONFIG, ou ~/.config/claude-provision/config.json.

Idempotent ; silencieux quand tout est en place ; journal des actions dans <etat>/provision.log.
A lancer a la main, par un minuteur (cron, systemd, tache planifiee) ou avant le demarrage d'un compte.

  python3 provisionner.py [--config FICHIER] [--compte DOSSIER] [--verifier]
    --compte   : provisionne ce dossier ~/.claude* meme s'il est encore vide
    --verifier : n'ecrit rien, liste ce qui serait fait (code 1 s'il y a quelque chose a faire)
"""
import datetime
import hashlib
import json
import os
import shutil
import sys
import time

WIN = os.name == 'nt'
HOME = os.path.expanduser('~')
SEP = ';' if WIN else ':'  # separateur de CLAUDE_CODE_PLUGIN_DIRS (celui des listes de chemins de l'OS)
NE_PAS_TOUCHER = {'.claude-sync-sauvegardes'}


def chemin_config():
    if '--config' in sys.argv:
        return sys.argv[sys.argv.index('--config') + 1]
    return os.environ.get('PROVISION_CONFIG') or os.path.join(HOME, '.config', 'claude-provision', 'config.json')


def charger_config():
    p = os.path.expanduser(chemin_config())
    try:
        with open(p, encoding='utf-8-sig') as f:
            c = json.load(f)
    except OSError:
        sys.exit(f'provisionner : fichier de configuration introuvable ({p}). Copie provisionner.exemple.json et adapte-le.')
    except ValueError as e:
        sys.exit(f'provisionner : configuration illisible ({p}) : {e}')
    rel = os.path.dirname(os.path.abspath(p))

    def chemin(cle, obligatoire=False):
        v = c.get(cle)
        if not v:
            if obligatoire:
                sys.exit(f'provisionner : « {cle} » manque dans {p}')
            return None
        v = os.path.expanduser(os.path.expandvars(v))
        return v if os.path.isabs(v) else os.path.normpath(os.path.join(rel, v))

    return {
        'skills': chemin('skills', True),             # dossier de skills partage (relie a ~/.claude*/skills)
        'global': chemin('claude_md', True),          # CLAUDE.md global
        'machine': chemin('machine_md'),              # partie propre a la machine -> ~/.claude-machine.md (facultatif)
        'mods': chemin('mods'),                       # dossier qui contient un dossier par mod (facultatif)
        'etat': chemin('etat', True),                 # journal, sauvegardes, empreintes
        'memoire': chemin('memoire'),                 # autoMemoryDirectory (facultatif)
        'plafond_skills': str(c['plafond_skills']) if c.get('plafond_skills') else None,
        'exclus': list(c.get('exclus', [])),          # dossiers ~/.claude* a ne jamais toucher
        'isoles': list(c.get('isoles', [])),          # comptes qui ne partagent ni regles ni memoire (voir README)
    }


CONF = charger_config()
SKILLS, GLOBAL, MODS = CONF['skills'], CONF['global'], CONF['mods']
ETAT = os.environ.get('PROVISION_ETAT') or CONF['etat']  # surcharge : tests seulement
VERIFIER = '--verifier' in sys.argv
actions, erreurs = [], []


def h(chemin):
    with open(chemin, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def noter(texte):
    actions.append(texte)


def sauvegarder(chemin, compte, quoi):
    """Deplace (ou copie) un fichier/dossier remplace dans <etat>/sauvegardes/<date>/."""
    dest_dir = os.path.join(ETAT, 'sauvegardes', datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f'{compte}-{quoi}')
    if os.path.isdir(chemin) and not os.path.islink(chemin):
        shutil.move(chemin, dest)
    else:
        shutil.copy2(chemin, dest)
    return dest


def est_lien(chemin):
    if os.path.islink(chemin):
        return True
    if WIN and os.path.isdir(chemin):
        try:
            import stat
            return bool(os.lstat(chemin).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except (AttributeError, OSError):
            return False
    return False


def meme(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def lier_dossier(cible, lien):
    if WIN:
        import _winapi
        _winapi.CreateJunction(cible, lien)
    else:
        os.symlink(cible, lien)


def retirer_lien(lien):
    if WIN and os.path.isdir(lien):
        os.rmdir(lien)  # supprime la jonction, jamais son contenu
    else:
        os.unlink(lien)


def lier_fichier(cible, lien):
    """Lien symbolique ; False si l'OS le refuse (Windows sans privilege) -> mode copie."""
    if os.environ.get('PROVISION_FORCER_COPIE'):  # tests du mode copie (Windows sans privilege)
        return False
    try:
        os.symlink(cible, lien)
        return True
    except (OSError, NotImplementedError):
        return False


def etat_lu(cle):
    p = os.path.join(ETAT, 'empreintes', cle)
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return None


def etat_ecrit(cle, valeur):
    if VERIFIER:
        return
    d = os.path.join(ETAT, 'empreintes')
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, cle), 'w') as f:
        f.write(valeur)


def ecrire(chemin, contenu_bytes):
    tmp = chemin + '.provision-tmp'
    with open(tmp, 'wb') as f:
        f.write(contenu_bytes)
    os.replace(tmp, chemin)


# ---------------------------------------------------------------- skills
def assurer_skills(d, compte):
    lien = os.path.join(d, 'skills')
    if meme(lien, SKILLS):
        return
    if VERIFIER:
        return noter(f'{compte}: skills -> {SKILLS}')
    if os.path.lexists(lien):
        if est_lien(lien):
            retirer_lien(lien)
        else:
            dest = sauvegarder(lien, compte, 'skills')
            noter(f'{compte}: ancien dossier skills sauvegarde dans {dest}')
    lier_dossier(SKILLS, lien)
    noter(f'{compte}: skills -> {SKILLS}')


# ---------------------------------------------------------------- CLAUDE.md
def assurer_fichier(lien, source, cle, compte, quoi, remonter):
    """Garantit que `lien` est le fichier `source` (lien, sinon copie a jour).

    remonter=True : une modification faite dans la copie du compte est recopiee dans la
    source (le global) au lieu d'etre ecrasee ; conflit (les deux modifies) -> sauvegarde.
    """
    if meme(lien, source) and os.path.exists(lien):
        etat_ecrit(cle, h(source))
        return
    hs = h(source)
    connu = etat_lu(cle)
    if os.path.lexists(lien) and not os.path.exists(lien):  # lien casse
        if VERIFIER:
            return noter(f'{compte}: {quoi} lien casse a refaire')
        os.unlink(lien)
    if os.path.exists(lien):
        hl = h(lien)
        if hl == hs:
            etat_ecrit(cle, hs)  # copie identique (mode copie) : rien a faire
            return
        elif remonter and connu and hs == connu and hl != connu:
            if VERIFIER:
                return noter(f'{compte}: {quoi} modifie dans le compte -> a remonter dans le global')
            with open(lien, 'rb') as f:
                ecrire(source, f.read())
            hs = h(source)
            noter(f'{compte}: {quoi} modifie dans le compte, recopie dans le global {source}')
        elif connu and hl == connu:
            pass  # copie non modifiee, source plus recente : on remplace
        else:
            if VERIFIER:
                return noter(f'{compte}: {quoi} different du global -> sauvegarde puis remplacement')
            dest = sauvegarder(lien, compte, quoi)
            if connu:
                erreurs.append(f'{compte}: CONFLIT {quoi} (compte et global modifies) ; version du compte gardee dans {dest}')
            noter(f'{compte}: ancien {quoi} sauvegarde dans {dest}')
        if VERIFIER:
            return noter(f'{compte}: {quoi} -> {source}')
        os.unlink(lien)
    elif VERIFIER:
        return noter(f'{compte}: {quoi} -> {source}')
    if lier_fichier(source, lien):
        noter(f'{compte}: {quoi} -> lien vers {source}')
    else:
        shutil.copy2(source, lien)
        noter(f'{compte}: {quoi} -> copie de {source} (lien refuse par l\'OS)')
    etat_ecrit(cle, hs)


# ---------------------------------------------------------------- settings.json
IGNORES = {'node_modules', '.git', '__pycache__'}


def fichiers_mod(racine):
    """Fichiers d'un mod, hors genere/local (.claude-plugin/types, node_modules, .git)."""
    out = []
    for base, dirs, files in os.walk(racine):
        rel = os.path.relpath(base, racine)
        dirs[:] = [x for x in dirs if x not in IGNORES and not (rel == '.claude-plugin' and x == 'types')]
        for f in files:
            out.append(os.path.normpath(os.path.join(rel, f)))
    return sorted(out)


def empreinte_mod(racine):
    m = hashlib.sha256()
    dernier = 0.0
    for rel in fichiers_mod(racine):
        p = os.path.join(racine, rel)
        m.update(rel.replace('\\', '/').encode())
        with open(p, 'rb') as f:
            m.update(hashlib.sha256(f.read()).digest())
        dernier = max(dernier, os.path.getmtime(p))
    return m.hexdigest(), dernier


def importer_dev_mods():
    """Filet : un mod developpe dans ~/.claude*/dev-mods/<session>/<mod>/ (dossier de session du
    skill plugin-authoring) finit dans le clone des mods, donc sauvegarde et synchronise.
    Pour chaque nom, la copie de dev la plus recente remplace celle du clone si elle est plus
    recente et differente (l'ancienne reste dans l'historique git). Les copies de dev ne sont
    jamais modifiees (une session peut les utiliser)."""
    candidats = {}
    vus = set()
    for nom in os.listdir(HOME):
        dev = os.path.join(HOME, nom, 'dev-mods')
        if not nom.startswith('.claude') or not os.path.isdir(dev):
            continue
        reel = os.path.normcase(os.path.realpath(dev))
        if reel in vus:
            continue
        vus.add(reel)
        for session in os.listdir(dev):
            sd = os.path.join(dev, session)
            if not os.path.isdir(sd):
                continue
            for mod in os.listdir(sd):
                md = os.path.join(sd, mod)
                manifeste = os.path.join(md, '.claude-plugin', 'plugin.json')
                if not os.path.isfile(manifeste):
                    continue
                try:
                    with open(manifeste, encoding='utf-8-sig') as f:
                        json.load(f)
                    emp, quand = empreinte_mod(md)
                except (OSError, ValueError):
                    continue  # mod en cours d'ecriture : au passage suivant
                if mod not in candidats or quand > candidats[mod][2]:
                    candidats[mod] = (md, emp, quand)
    depuis = etat_lu('filet-dev-mods-depuis')  # date d'installation du filet : avant, rien n'est suivi
    if depuis is None:
        depuis = str(time.time())
        etat_ecrit('filet-dev-mods-depuis', depuis)
    depuis = float(depuis)
    for mod, (md, emp, quand) in sorted(candidats.items()):
        cible = os.path.join(MODS, mod)
        cle = 'dev-' + hashlib.sha256(os.path.normcase(md).encode()).hexdigest()[:16]
        connu = etat_lu(cle)
        etat_ecrit(cle, emp)
        if os.path.isdir(cible):
            emp_c, quand_c = empreinte_mod(cible)
            # Mod deja au depot : on ne suit une copie de dev que si elle a change depuis le passage
            # precedent (une vieille copie de dev ne remplace jamais le depot).
            if emp_c == emp or quand <= quand_c or connu == emp or (connu is None and quand <= depuis):
                continue
            quoi = f'mod {mod} mis a jour depuis {md}'
        else:
            quoi = f'mod {mod} importe depuis {md}'
        if VERIFIER:
            noter(quoi)
            continue
        tmp = cible + '.import-tmp'
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        os.makedirs(tmp)
        for rel in fichiers_mod(md):
            os.makedirs(os.path.dirname(os.path.join(tmp, rel)), exist_ok=True)
            shutil.copy2(os.path.join(md, rel), os.path.join(tmp, rel))
        if os.path.isdir(cible):
            for rel in fichiers_mod(cible):  # ce qui n'existe plus dans la copie de dev disparait (git le garde)
                if not os.path.exists(os.path.join(tmp, rel)):
                    os.remove(os.path.join(cible, rel))
        for rel in fichiers_mod(tmp):
            os.makedirs(os.path.dirname(os.path.join(cible, rel)), exist_ok=True)
            shutil.copy2(os.path.join(tmp, rel), os.path.join(cible, rel))
        shutil.rmtree(tmp)
        noter(quoi)


def liste_mods():
    """Mods du dossier des mods ; un fichier retenus.json {"retenus": {"nom": "raison"}} met des mods de cote."""
    retenus = {}
    try:
        with open(os.path.join(MODS, 'retenus.json'), encoding='utf-8') as f:
            retenus = json.load(f).get('retenus', {})
    except (OSError, ValueError):
        pass
    mods = []
    for nom in sorted(os.listdir(MODS)):
        if nom in retenus:
            continue
        if os.path.isfile(os.path.join(MODS, nom, '.claude-plugin', 'plugin.json')):
            mods.append(os.path.join(MODS, nom))
    return mods


def sous(racine, chemin):
    r = os.path.normcase(os.path.normpath(racine))
    c = os.path.normcase(os.path.normpath(os.path.expanduser(chemin)))
    return c == r or c.startswith(r + os.sep)


def isole(d):
    """Compte « isole » (par exemple un compte fourni par un employeur, qui ne doit voir ni tes regles
    personnelles ni ta memoire partagee). Rend l'entree de configuration qui le designe, sinon None.
    Une entree : {"dossier": "mot du nom du dossier", "courriel": "@domaine.exemple", "claude_md": "regles propres"}."""
    nom = os.path.basename(d.rstrip('/\\')).lower()
    courriel = None
    for entree in CONF['isoles']:
        mot = (entree.get('dossier') or '').lower()
        if mot and mot in nom:
            return entree
        suffixe = (entree.get('courriel') or '').lower()
        if suffixe:
            if courriel is None:
                try:
                    with open(os.path.join(d, '.claude.json'), encoding='utf-8') as f:
                        courriel = ((json.load(f).get('oauthAccount') or {}).get('emailAddress') or '').lower()
                except (OSError, ValueError):
                    courriel = ''
            if courriel.endswith(suffixe):
                return entree
    return None


def assurer_settings(d, compte, mods):
    p = os.path.join(d, 'settings.json')
    data = {}
    if os.path.exists(p):
        try:
            with open(p, encoding='utf-8-sig') as f:
                data = json.load(f)
        except ValueError as e:
            erreurs.append(f'{compte}: settings.json illisible ({e}), non modifie')
            return
        if not isinstance(data, dict):
            erreurs.append(f'{compte}: settings.json n\'est pas un objet, non modifie')
            return
    env = data.get('env') if isinstance(data.get('env'), dict) else {}
    avant = env.get('CLAUDE_CODE_PLUGIN_DIRS', '')
    autres = [x for x in avant.split(SEP) if x.strip() and not sous(MODS, x)] if mods else []  # dossiers hors du dossier des mods : gardes
    voulu = SEP.join(mods + autres)
    # Plafond de la liste des skills (facultatif) : au plafond par defaut (1 % du contexte), Claude Code retire
    # la description des skills les moins utilises, qu'il ne sait alors plus choisir. Valeur fixe en caracteres.
    souhaits = [('CLAUDE_CODE_PLUGIN_DIRS', voulu)] if mods else []
    if CONF['plafond_skills']:
        souhaits.append(('SLASH_COMMAND_TOOL_CHAR_BUDGET', CONF['plafond_skills']))
    changements = {k: v for k, v in souhaits if env.get(k) != v}
    # Memoire automatique partagee (facultatif) : un dossier commun a tous les comptes, jamais pour un compte isole.
    if CONF['memoire'] or isole(d):
        pref = None if isole(d) else CONF['memoire']
        if data.get('autoMemoryDirectory') != pref:
            changements['autoMemoryDirectory'] = pref
    # ~/.claude/settings.json sert aussi de reglage de PROJET pour tout ce qui demarre dans ~ : un compte isole
    # y verrait la memoire partagee. Il ne peut pas l'ecraser (le projet passe avant l'utilisateur), donc on coupe
    # sa memoire automatique.
    if isole(d) and env.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY') != '1':
        changements['CLAUDE_CODE_DISABLE_AUTO_MEMORY'] = '1'
    # Meme detour pour le CLAUDE.md : ~/.claude/CLAUDE.md (le global) est aussi le CLAUDE.md de projet de ~.
    exclus_md = [os.path.join(HOME, '.claude', 'CLAUDE.md'), GLOBAL] if isole(d) else []
    deja = data.get('claudeMdExcludes') if isinstance(data.get('claudeMdExcludes'), list) else []
    if exclus_md and not all(x in deja for x in exclus_md):
        data['claudeMdExcludes'] = deja + [x for x in exclus_md if x not in deja]
        changements['claudeMdExcludes'] = 'global exclu'
    if not changements:
        return
    if VERIFIER:
        return noter(f'{compte}: ' + ' ; '.join(f'{k} « {env.get(k, "")} » -> « {v} »' for k, v in changements.items()))
    if os.path.exists(p) and not etat_lu(f'{compte}.settings-sauvegarde'):
        dest = sauvegarder(p, compte, 'settings.json')
        etat_ecrit(f'{compte}.settings-sauvegarde', dest)
    pref_change = changements.pop('autoMemoryDirectory', 'inchange')
    if pref_change is None:
        data.pop('autoMemoryDirectory', None)
    elif pref_change != 'inchange':
        data['autoMemoryDirectory'] = pref_change
    md_change = changements.pop('claudeMdExcludes', None)
    env.update(changements)
    data['env'] = env
    if md_change:
        changements['claudeMdExcludes'] = md_change
    if pref_change != 'inchange':
        changements['autoMemoryDirectory'] = pref_change
    ecrire(p, (json.dumps(data, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))
    noter(f'{compte}: ' + ' ; '.join(f'{k} = {v}' for k, v in changements.items()))


# ---------------------------------------------------------------- comptes
def est_compte(d):
    return any(os.path.exists(os.path.join(d, x)) for x in ('.credentials.json', 'settings.json', 'projects'))


def comptes(force):
    vus = []
    for nom in sorted(os.listdir(HOME)):
        d = os.path.join(HOME, nom)
        if not nom.startswith('.claude') or nom in NE_PAS_TOUCHER or nom in CONF['exclus']:
            continue
        if not os.path.isdir(d) or est_lien(d) or not est_compte(d):
            continue
        vus.append(d)
    if force:
        f = os.path.abspath(os.path.expanduser(force))
        if os.path.normcase(os.path.dirname(f)) != os.path.normcase(HOME) or not os.path.basename(f).startswith('.claude'):
            erreurs.append(f'--compte {f} ignore : seuls les dossiers ~/.claude* de cet utilisateur sont provisionnes')
        elif os.path.basename(f) in CONF['exclus']:
            pass
        elif not any(meme(f, v) for v in vus):
            if not VERIFIER:
                os.makedirs(f, exist_ok=True)
            vus.append(f)
    return vus


def verrouiller():
    """Un seul provisionnement a la fois (synchros skills et mods lancees a la meme seconde)."""
    os.makedirs(ETAT, exist_ok=True)
    f = open(os.path.join(ETAT, 'provision.lock'), 'a+')
    fin = time.time() + 60
    while True:
        try:
            if WIN:
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError:
            if time.time() > fin:
                sys.exit(0)  # un autre passage tourne encore : le suivant fera le travail
            time.sleep(0.5)


def main():
    force = None
    if '--compte' in sys.argv:
        force = sys.argv[sys.argv.index('--compte') + 1]
    if not os.path.isfile(GLOBAL):
        sys.exit(f'provisionner : global absent ({GLOBAL})')
    if not VERIFIER:
        verrou = verrouiller()  # noqa: F841 (garde le verrou jusqu'a la fin du processus)
    if CONF['machine']:
        try:
            assurer_fichier(os.path.join(HOME, '.claude-machine.md'), CONF['machine'], 'machine.md', 'machine', 'claude-machine.md', remonter=False)
        except OSError as e:
            erreurs.append(f'machine: ~/.claude-machine.md : {e}')
    if MODS and os.path.isdir(MODS):
        try:
            importer_dev_mods()
        except OSError as e:
            erreurs.append(f'import des dev-mods : {e}')
    mods = liste_mods() if MODS and os.path.isdir(MODS) else []
    if MODS and not mods:
        erreurs.append(f'aucun mod trouve dans {MODS}')
    for d in comptes(force):
        compte = os.path.basename(d.rstrip('/\\'))
        if VERIFIER and not os.path.isdir(d):
            noter(f'{compte}: dossier a creer')
            continue
        for etape in (lambda: assurer_skills(d, compte),
                      lambda: assurer_fichier(os.path.join(d, 'CLAUDE.md'), (os.path.expanduser((isole(d) or {}).get('claude_md') or '') or GLOBAL) if isole(d) else GLOBAL,
                                              f'{compte}.CLAUDE.md', compte, 'CLAUDE.md', remonter=True),
                      lambda: assurer_settings(d, compte, mods)):
            try:
                etape()
            except OSError as e:
                erreurs.append(f'{compte}: {e}')
    horodatage = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    if VERIFIER:
        for a in actions + erreurs:
            print(a)
        sys.exit(1 if actions or erreurs else 0)
    if actions or erreurs:
        with open(os.path.join(ETAT, 'provision.log'), 'a', encoding='utf-8') as f:
            for a in actions:
                f.write(f'{horodatage} {a}\n')
            for e in erreurs:
                f.write(f'{horodatage} ERREUR {e}\n')
    err = os.path.join(ETAT, 'provision.error')
    if erreurs:
        with open(err, 'w', encoding='utf-8') as f:
            f.write('\n'.join(f'{horodatage} {e}' for e in erreurs) + '\n')
        for e in erreurs:
            print('provisionner :', e, file=sys.stderr)
        sys.exit(1)
    if os.path.exists(err):
        os.remove(err)
    with open(os.path.join(ETAT, 'provision.success'), 'w') as f:
        f.write(horodatage + '\n')


if __name__ == '__main__':
    main()
