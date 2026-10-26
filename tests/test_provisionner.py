"""Tests de provisionner.py dans un faux dossier personnel (aucun vrai compte touché).
Lancer : python3 -m unittest discover -s tests -v"""
import json, os, subprocess, sys, tempfile, unittest

ICI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ICI, 'provisionner.py')


def ecrire(chemin, texte=''):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, 'w', encoding='utf-8') as f:
        f.write(texte)


class Provision(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.t.name, 'home')
        cfg = os.path.join(self.t.name, 'cfg')
        ecrire(os.path.join(cfg, 'skills', 'bonjour', 'SKILL.md'), '---\nname: bonjour\n---\n')
        ecrire(os.path.join(cfg, 'CLAUDE.md'), '# global\n')
        ecrire(os.path.join(cfg, 'CLAUDE.travail.md'), '# travail\n')
        ecrire(os.path.join(cfg, 'machine.md'), '# machine\n')
        ecrire(os.path.join(cfg, 'mods', 'mon-mod', '.claude-plugin', 'plugin.json'), '{"name":"mon-mod"}')
        ecrire(os.path.join(cfg, 'mods', 'ecarte', '.claude-plugin', 'plugin.json'), '{"name":"ecarte"}')
        ecrire(os.path.join(cfg, 'mods', 'retenus.json'), '{"retenus": {"ecarte": "essai"}}')
        for compte in ('.claude', '.claude-perso', '.claude-travail', '.claude-test'):
            ecrire(os.path.join(self.home, compte, 'settings.json'), '{"theme": "dark"}' if compte != '.claude-test' else '{}')
        self.cfg = cfg
        self.conf = os.path.join(cfg, 'config.json')
        with open(self.conf, 'w') as f:
            json.dump({'skills': 'skills', 'claude_md': 'CLAUDE.md', 'machine_md': 'machine.md', 'mods': 'mods',
                       'etat': os.path.join(self.t.name, 'etat'), 'memoire': os.path.join(cfg, 'memoire'),
                       'plafond_skills': 200000, 'exclus': ['.claude-test'],
                       'isoles': [{'dossier': 'travail', 'claude_md': os.path.join(cfg, 'CLAUDE.travail.md')}]}, f)

    def tearDown(self):
        self.t.cleanup()

    def lancer(self, *args):
        env = dict(os.environ, HOME=self.home, USERPROFILE=self.home)
        return subprocess.run([sys.executable, SCRIPT, '--config', self.conf, *args], env=env, capture_output=True, text=True)

    def settings(self, compte):
        with open(os.path.join(self.home, compte, 'settings.json'), encoding='utf-8') as f:
            return json.load(f)

    def test_liens_et_reglages(self):
        r = self.lancer()
        self.assertEqual(r.returncode, 0, r.stderr)
        for compte in ('.claude', '.claude-perso'):
            self.assertEqual(os.path.realpath(os.path.join(self.home, compte, 'skills')), os.path.realpath(os.path.join(self.cfg, 'skills')))
            self.assertEqual(os.path.realpath(os.path.join(self.home, compte, 'CLAUDE.md')), os.path.realpath(os.path.join(self.cfg, 'CLAUDE.md')))
            s = self.settings(compte)
            self.assertEqual(s['theme'], 'dark')  # les autres réglages ne bougent pas
            self.assertEqual(s['env']['CLAUDE_CODE_PLUGIN_DIRS'], os.path.join(self.cfg, 'mods', 'mon-mod'))  # le mod écarté n'y est pas
            self.assertEqual(s['env']['SLASH_COMMAND_TOOL_CHAR_BUDGET'], '200000')
            self.assertEqual(s['autoMemoryDirectory'], os.path.join(self.cfg, 'memoire'))
        self.assertEqual(os.path.realpath(os.path.join(self.home, '.claude-machine.md')), os.path.realpath(os.path.join(self.cfg, 'machine.md')))

    def test_compte_exclu_intact(self):
        self.lancer()
        self.assertFalse(os.path.exists(os.path.join(self.home, '.claude-test', 'CLAUDE.md')))
        self.assertEqual(self.settings('.claude-test'), {})

    def test_compte_isole(self):
        self.lancer()
        d = os.path.join(self.home, '.claude-travail')
        self.assertEqual(os.path.realpath(os.path.join(d, 'CLAUDE.md')), os.path.realpath(os.path.join(self.cfg, 'CLAUDE.travail.md')))
        s = self.settings('.claude-travail')
        self.assertNotIn('autoMemoryDirectory', s)
        self.assertEqual(s['env']['CLAUDE_CODE_DISABLE_AUTO_MEMORY'], '1')
        self.assertIn(os.path.join(self.cfg, 'CLAUDE.md'), s['claudeMdExcludes'])

    def test_idempotent_et_verifier(self):
        self.assertEqual(self.lancer('--verifier').returncode, 1)  # il y a du travail, rien n'est écrit
        self.assertFalse(os.path.exists(os.path.join(self.home, '.claude-perso', 'CLAUDE.md')))
        self.assertEqual(self.lancer().returncode, 0)
        self.assertEqual(self.lancer('--verifier').returncode, 0)  # plus rien à faire

    def test_modification_dans_le_compte_remonte(self):
        self.lancer()
        # Mode copie (lien refusé) : une modification faite dans le compte remonte dans le global.
        env = dict(os.environ, HOME=self.home, USERPROFILE=self.home, PROVISION_FORCER_COPIE='1')
        d = os.path.join(self.home, '.claude-perso')
        os.unlink(os.path.join(d, 'CLAUDE.md'))
        subprocess.run([sys.executable, SCRIPT, '--config', self.conf], env=env, check=True)
        self.assertFalse(os.path.islink(os.path.join(d, 'CLAUDE.md')))
        ecrire(os.path.join(d, 'CLAUDE.md'), '# global\n+ une règle ajoutée dans le compte\n')
        subprocess.run([sys.executable, SCRIPT, '--config', self.conf], env=env, check=True)
        with open(os.path.join(self.cfg, 'CLAUDE.md'), encoding='utf-8') as f:
            self.assertIn('une règle ajoutée', f.read())


if __name__ == '__main__':
    unittest.main()
