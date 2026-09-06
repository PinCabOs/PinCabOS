#!/usr/bin/env python3
"""L'unique écrivain des fichiers INI de PinCabOS (PINCABOS_INI_UNIQUE_V1).

VPinballX.ini et vpinfe.ini étaient modifiés par six copies différentes de la
même logique (topologie, WebApp GPU, WebApp audio, audio de l'installateur, DOF,
page Écran en configparser qui réécrivait tout le fichier). Chacune avait sa
façon d'insérer une clé, de créer une section, de commenter, d'écrire : un
écrivain pouvait défaire ce qu'un autre venait de poser. Ici, une seule
implémentation ; les modules de domaine produisent des valeurs, ce module les
pose.

Contrat :
- le texte est conservé tel quel (commentaires, ordre, casse, lignes vides) ;
- section et clé se comparent sans tenir compte de la casse, la casse écrite
  est celle de l'appelant pour une clé nouvelle, celle du fichier pour une clé
  existante ;
- une clé nouvelle se pose en fin de section, avant les lignes vides qui la
  terminent ; une section nouvelle se crée en fin de fichier ;
- `commentaire` pose une ligne au-dessus de la clé et remplace un commentaire
  PinCabOS déjà là (« par PinCabOS fonction(…) ») : jamais deux commentaires ;
- l'écriture est atomique (fichier temporaire puis renommage), garde le mode,
  rend le fichier au joueur, et ne touche pas le disque si rien n'a changé.
"""
import re
import os
import sys
import tempfile
from pathlib import Path

MARQUE_COMMENTAIRE = "par PinCabOS fonction("
# en-tete de section, pour reconnaitre un fichier colle sur une seule ligne
_ENTETE = re.compile(r"\[[A-Za-z][A-Za-z0-9_. -]*\]")

try:
    from pincabos_paths import PATHS
    VPX_INI = Path(PATHS.vpx_ini)
    VPINFE_INI = Path(PATHS.vpinfe_ini)
    _UID, _GID = PATHS.uid_int(), PATHS.gid_int()
except Exception:   # hors cab (tests, banc) : chemins par defaut
    VPX_INI = Path("/home/pinball/.pincabos/vpx/VPinballX.ini")
    VPINFE_INI = Path("/home/pinball/.config/vpinfe/vpinfe.ini")
    _UID, _GID = 1000, 1000


def _est_entete(ligne: str) -> bool:
    s = ligne.strip()
    return s.startswith("[") and s.endswith("]")


def _nom_section(ligne: str) -> str:
    return ligne.strip()[1:-1].strip()


def _est_cle(ligne: str, cle: str) -> bool:
    s = ligne.strip()
    if not s or s.startswith((";", "#")) or "=" not in s:
        return False
    return s.split("=", 1)[0].strip().lower() == cle.lower()


class Ini:
    """Un fichier INI vu comme des lignes, modifiable sans rien perdre."""

    def __init__(self, texte: str = ""):
        self.lignes = texte.split("\n") if texte else []
        self._fin_de_ligne = texte.endswith("\n") if texte else True
        if self.lignes and self.lignes[-1] == "" and self._fin_de_ligne:
            self.lignes.pop()

    # -------------------------------------------------------------- lecture
    def sections(self) -> list:
        return [_nom_section(l) for l in self.lignes if _est_entete(l)]

    def bornes(self, section: str):
        """(début, fin) : indice de l'en-tête et indice de la prochaine en-tête (ou len) ; (None, None) si absente."""
        return self._bornes(section)

    def _bornes(self, section: str):
        """(début, fin) : indice de l'en-tête et indice de la prochaine en-tête (ou len)."""
        debut = None
        for i, l in enumerate(self.lignes):
            if _est_entete(l):
                if debut is not None:
                    return debut, i
                if _nom_section(l).lower() == section.lower():
                    debut = i
        return (debut, len(self.lignes)) if debut is not None else (None, None)

    def get(self, section: str, cle: str, defaut=None):
        debut, fin = self._bornes(section)
        if debut is None:
            return defaut
        for l in self.lignes[debut + 1:fin]:
            if _est_cle(l, cle):
                return l.split("=", 1)[1].strip()
        return defaut

    def cles(self, section: str) -> dict:
        debut, fin = self._bornes(section)
        out = {}
        if debut is None:
            return out
        for l in self.lignes[debut + 1:fin]:
            s = l.strip()
            if s and not s.startswith((";", "#")) and "=" in s:
                k, v = s.split("=", 1)
                out.setdefault(k.strip(), v.strip())
        return out

    # -------------------------------------------------------------- écriture
    def poser(self, section: str, cle: str, valeur, commentaire: str | None = None, purger_commentaire: bool = False) -> bool:
        """Pose `cle = valeur` dans [section]. Renvoie True si le texte a changé.
        `purger_commentaire` : retire un commentaire PinCabOS posé au-dessus de la clé
        (INI officiels VPX / VPinFE que l'on ne veut pas polluer)."""
        valeur = "" if valeur is None else str(valeur)
        debut, fin = self._bornes(section)
        if debut is None:
            if self.lignes and self.lignes[-1].strip():
                self.lignes.append("")
            if commentaire:
                self.lignes.append(commentaire)
            self.lignes += [f"[{section}]", f"{cle} = {valeur}"]
            return True
        for i in range(debut + 1, fin):
            if _est_cle(self.lignes[i], cle):
                nom = self.lignes[i].split("=", 1)[0].strip()
                nouvelle = f"{nom} = {valeur}"
                change = self.lignes[i] != nouvelle
                self.lignes[i] = nouvelle
                if commentaire:
                    if i > 0 and MARQUE_COMMENTAIRE in self.lignes[i - 1]:
                        change = change or self.lignes[i - 1] != commentaire
                        self.lignes[i - 1] = commentaire
                    else:
                        self.lignes.insert(i, commentaire)
                        change = True
                elif purger_commentaire and i > debut + 1 and MARQUE_COMMENTAIRE in self.lignes[i - 1]:
                    del self.lignes[i - 1]
                    change = True
                return change
        # clé absente : en fin de section, avant les lignes vides qui la terminent
        j = fin
        while j > debut + 1 and not self.lignes[j - 1].strip():
            j -= 1
        nouvelles = ([commentaire] if commentaire else []) + [f"{cle} = {valeur}"]
        self.lignes[j:j] = nouvelles
        return True

    def poser_section(self, section: str, valeurs: dict, commentaire: str | None = None) -> bool:
        change = False
        for cle, valeur in valeurs.items():
            change = self.poser(section, cle, valeur, commentaire) or change
        return change

    def poser_partout(self, cle: str, valeur) -> bool:
        """Remplace `cle` dans TOUTES les sections où elle existe (clés VPinFE
        recopiées dans plusieurs sections) ; l'ajoute en fin de fichier sinon."""
        valeur = "" if valeur is None else str(valeur)
        change, trouve = False, False
        for i, l in enumerate(self.lignes):
            if _est_cle(l, cle):
                trouve = True
                nom = l.split("=", 1)[0].strip()
                nouvelle = f"{nom} = {valeur}"
                change = change or l != nouvelle
                self.lignes[i] = nouvelle
        if not trouve:
            self.lignes.append(f"{cle} = {valeur}")
            change = True
        return change

    def supprimer(self, section: str, cle: str) -> bool:
        debut, fin = self._bornes(section)
        if debut is None:
            return False
        for i in range(debut + 1, fin):
            if _est_cle(self.lignes[i], cle):
                del self.lignes[i]
                if i > debut + 1 and MARQUE_COMMENTAIRE in self.lignes[i - 1]:
                    del self.lignes[i - 1]
                return True
        return False

    def texte(self) -> str:
        if not self.lignes:
            return ""
        return "\n".join(self.lignes) + ("\n" if self._fin_de_ligne else "")


# ------------------------------------------------------------------ fichiers
def lire(chemin) -> Ini:
    chemin = Path(chemin)
    return Ini(chemin.read_text(encoding="utf-8", errors="replace")) if chemin.is_file() else Ini("")


def est_aplati(texte: str) -> bool:
    """Un INI dont une ligne porte plusieurs sections ET plusieurs affectations :
    le fichier a ete colle sur une seule ligne (PINCABOS_INI_APLATI_V1) et plus
    aucune section n'y est lisible. Une valeur qui contient des crochets n'en est pas.
    """
    for ligne in texte.split(chr(10)):
        if len(_ENTETE.findall(ligne)) > 1 and ligne.count(" = ") > 1:
            return True
    return False


def ecrire_texte(chemin, texte: str, proprietaire=(None, None)) -> bool:
    """Écriture atomique ; rien si identique ; mode conservé ; propriétaire (uid, gid) ou celui du joueur."""
    chemin = Path(chemin)
    # PINCABOS_INI_APLATI_V1 : mieux vaut une erreur qu'un fichier de configuration detruit
    if est_aplati(texte):
        raise ValueError("INI aplati (plusieurs sections sur une ligne) : "
                         + str(chemin) + " non ecrit - PINCABOS_INI_APLATI_V1")
    ancien = chemin.read_text(encoding="utf-8", errors="replace") if chemin.is_file() else None
    if ancien == texte:
        return False
    chemin.parent.mkdir(parents=True, exist_ok=True)
    stat = chemin.stat() if chemin.is_file() else None
    fd, tmp = tempfile.mkstemp(prefix=f".{chemin.name}.", dir=str(chemin.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texte)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, (stat.st_mode & 0o777) if stat else 0o644)
        uid, gid = proprietaire
        if uid is None:
            uid, gid = (stat.st_uid, stat.st_gid) if stat else (_UID, _GID)
        if os.geteuid() == 0:
            try:
                os.chown(tmp, uid, gid)
            except OSError:
                pass
        os.replace(tmp, chemin)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def ecrire(chemin, ini: Ini, proprietaire=(None, None)) -> bool:
    return ecrire_texte(chemin, ini.texte(), proprietaire)


def appliquer(chemin, changements: dict, commentaire: str | None = None, partout: dict | None = None) -> list:
    """changements = {section: {cle: valeur}} ; partout = {cle: valeur} (toutes sections).
    Une passe, une écriture. Journal : une ligne par clé changée, puis l'écriture."""
    chemin = Path(chemin)
    ini = lire(chemin)
    journal = []
    for section, valeurs in (changements or {}).items():
        for cle, valeur in valeurs.items():
            if ini.poser(section, cle, valeur, commentaire):
                journal.append(f"GO: [{section}] {cle} = {valeur}")
    for cle, valeur in (partout or {}).items():
        if ini.poser_partout(cle, valeur):
            journal.append(f"GO: {cle} = {valeur} (toutes sections)")
    if journal:
        try:
            ecrire(chemin, ini)
            journal.append(f"GO: {chemin} écrit")
        except OSError as exc:
            journal.append(f"NOGO: {chemin} non écrit ({exc})")
    else:
        journal.append(f"GO: {chemin} déjà à jour")
    return journal


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Lit / pose des clés dans un INI (écrivain unique PinCabOS)")
    ap.add_argument("fichier")
    ap.add_argument("--get", nargs=2, metavar=("SECTION", "CLE"))
    ap.add_argument("--set", nargs=3, action="append", metavar=("SECTION", "CLE", "VALEUR"), default=[])
    ap.add_argument("--commentaire", default=None)
    args = ap.parse_args(argv)
    if args.get:
        v = lire(args.fichier).get(*args.get)
        print("" if v is None else v)
        return 0 if v is not None else 1
    changements = {}
    for section, cle, valeur in args.set:
        changements.setdefault(section, {})[cle] = valeur
    for l in appliquer(args.fichier, changements, args.commentaire):
        print(l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
