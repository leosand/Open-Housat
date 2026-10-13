"""Classification des jalons de chantier / Construction milestone classifier.
M0 terrain nu -> M1 fondation -> M2 structure -> M3 toiture -> M4 finition.
Regles sur tendances d'indices (v0.1) ; U-Net siamois prevu en phase 2 (dette documentee).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Milestone(IntEnum):
    M0_TERRAIN = 0      # terrain nu, aucun travaux detecte
    M1_FONDATION = 1    # sol nu/excavation apparait (BSI en hausse)
    M2_STRUCTURE = 2    # emprise batie en croissance soutenue (NDBI en hausse)
    M3_TOITURE = 3      # emprise stabilisee, reflectance toiture (plateau NDBI)
    M4_FINITION = 4     # vegetation/amenagement revient, changements faibles


@dataclass
class MilestoneDecision:
    milestone: Milestone
    confidence: float
    low_confidence: bool  # True si fallback SR ou historique court


def classify(
    *,
    built_ratio: float,          # fraction de pixels batis sur la parcelle
    delta_ndbi_mean: float,      # tendance du bati vs observation precedente
    delta_bsi_mean: float,       # tendance du sol nu
    change_score_value: float,   # activite globale [0,1]
    sr_method: str,
) -> MilestoneDecision:
    low_conf = sr_method != "sen2sr"

    # M0 : rien ne bouge. La condition d'origine (`built_ratio < 0.02`) rendait M0 quasi
    # inatteignable — mesure du 2026-09-19 : une parcelle STABLE (score 0, dNDBI 0, dBSI 0) avec
    # 10 % de sol nu tombait dans le `else` conservateur et s'affichait « M1 fondation detectee »,
    # c'est-a-dire « des travaux ont commence » sur une parcelle ou il ne se passe rien. Le critere
    # d'origine est CONSERVE (parcelle sans bati), on ajoute le cas « aucun changement ».
    # Reserve mesuree a ce garde-fou : une parcelle DEJA BATIE et calme est un plateau (M3), pas un
    # terrain nu — d'ou le `built_ratio < 0.4`, sans quoi M0 avalait M3 (mesure : un plateau a 69 %
    # de bati sortait en « terrain nu »).
    quiet = (change_score_value < 0.02
             and abs(delta_ndbi_mean) <= 0.01 and abs(delta_bsi_mean) <= 0.01)
    if (quiet and built_ratio < 0.4) or (built_ratio < 0.02 and delta_bsi_mean <= 0.01):
        ms, conf = Milestone.M0_TERRAIN, 0.9
    elif delta_bsi_mean > 0.02 and built_ratio < 0.15:
        ms, conf = Milestone.M1_FONDATION, 0.75
    elif delta_ndbi_mean > 0.015 and built_ratio >= 0.15:
        ms, conf = Milestone.M2_STRUCTURE, 0.8
    elif built_ratio >= 0.4 and abs(delta_ndbi_mean) <= 0.015 and change_score_value < 0.08:
        ms, conf = Milestone.M3_TOITURE, 0.65  # plateau : toiture non separable a 2,5 m sans multi-angle
    elif change_score_value < 0.03 and delta_bsi_mean < 0:
        ms, conf = Milestone.M4_FINITION, 0.6
    else:
        ms, conf = Milestone.M1_FONDATION, 0.4  # etat ambigu : conservateur

    if low_conf:
        conf *= 0.7
    return MilestoneDecision(milestone=ms, confidence=round(conf, 2), low_confidence=low_conf)


def hold_milestone(candidate: Milestone, reached: Milestone | int) -> Milestone:
    """Le jalon ne regresse JAMAIS : un chantier ne se de-construit pas.

    Garde-fou de PRODUIT, pas de calcul. Mesure du 2026-06-09 (chantier #3, 40 observations) :
    le rail est passe M2 -> M1 -> M2 sur trois observations dont l'emprise valait
    0,2033 / 0,1794 / 0,1981 — les trois valeurs sont identiques a la precision de la mesure,
    seule une bascule de seuil avait change. Afficher « retour en fondations » sur un chantier
    qui n'a pas bouge est un mensonge par instabilite numerique.
    """
    return max(candidate, reached)
