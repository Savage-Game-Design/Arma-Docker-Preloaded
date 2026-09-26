from dataclasses import dataclass
from enum import Enum


class CDLCId(Enum):
    SPEARHEAD = 'spe'
    GLOBMOB = 'gm'
    CSLA = 'csla'
    SOG = 'vn'
    WS = 'ws'
    EF = 'ef'
    RF = 'rf'

@dataclass
class CDLC:
    id: CDLCId
    name: str
    depot: str

CDLCs = [
    CDLC(id=CDLCId.SPEARHEAD,  name='Spearhead 1944',        depot='233788'),
    CDLC(id=CDLCId.GLOBMOB,    name='Global Mobilization',   depot='233792'),
    CDLC(id=CDLCId.CSLA,       name='CSLA Iron Curtain',     depot='233793'),
    CDLC(id=CDLCId.SOG,        name='S.O.G. Prairie Fire',   depot='233794'),
    CDLC(id=CDLCId.WS,         name='Western Sahara',        depot='233795'),
    CDLC(id=CDLCId.EF,         name='Expeditionary Forces',  depot='233798'),
    CDLC(id=CDLCId.RF,         name='Reaction Forces',       depot='233799'),
]

CDLCsById = { cdlc.id.value: cdlc for cdlc in CDLCs }
