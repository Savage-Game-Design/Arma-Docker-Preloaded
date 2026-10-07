from dataclasses import dataclass


@dataclass
class CDLC:
    id: str
    name: str
    depot: str


# Keyed by the id used with -mod= and the CDLCS build arg.
CDLCS = {
    'spe':  CDLC(id='spe',  name='Spearhead 1944',       depot='233788'),
    'gm':   CDLC(id='gm',   name='Global Mobilization',  depot='233792'),
    'csla': CDLC(id='csla', name='CSLA Iron Curtain',    depot='233793'),
    'vn':   CDLC(id='vn',   name='S.O.G. Prairie Fire',  depot='233794'),
    'ws':   CDLC(id='ws',   name='Western Sahara',       depot='233795'),
    'ef':   CDLC(id='ef',   name='Expeditionary Forces', depot='233798'),
    'rf':   CDLC(id='rf',   name='Reaction Forces',      depot='233799'),
}
