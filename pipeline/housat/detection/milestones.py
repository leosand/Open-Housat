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

    if built_ratio < 0.02 and delta_bsi_mean <= 0.01:
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
