"""Independent arithmetic transcription of the owner-supplied legacy excerpt.

Trusted test oracle only. Does not import/execute pasted Python strategy code.
All signal inputs must already be completed, chronologically validated candles.
"""
from decimal import Decimal as D,localcontext

def snapshot(bars,hourly):
    with localcontext() as ctx:
        ctx.prec=34
        hi=[b.high for b in bars];lo=[b.low for b in bars];cl=[b.close for b in bars]
        swingH=max(hi[-25:-5]);swingL=min(lo[-25:-5])
        bullSweep=lo[-1]<swingL and cl[-1]>swingL
        bearSweep=hi[-1]>swingH and cl[-1]<swingH
        bullMSS=any(c>swingH for c in cl[-4:-1]);bearMSS=any(c<swingL for c in cl[-4:-1])
        bullFVG=lo[-1]>hi[-3];bearFVG=hi[-1]<lo[-3]
        side=('LONG' if bullSweep else 'SHORT') if bullSweep or bearSweep else None
        htf='LONG' if hourly[-1].close>sum((b.close for b in hourly),D(0))/21 else 'SHORT'
        hour=bars[-1].open_ms//3600000%24
        mss=(bullSweep and bullMSS) or (bearSweep and bearMSS)
        fvg=(bullSweep and bullFVG) or (bearSweep and bearFVG)
        score=(35+30*bool(mss)+15*bool(fvg)+10*(side==htf)+10*(8<=hour<22)) if side else 0
        trs=[max(hi[j]-lo[j],abs(hi[j]-cl[j-1]),abs(lo[j]-cl[j-1])) for j in range(1,len(bars))]
        stop=max(D('.008'),min(D('.03'),sum(trs[-14:])/14/cl[-1]*D('1.5')))
        return dict(signal_ms=bars[-1].open_ms+900000,original_side=side,
            executed_side=('SHORT' if side=='LONG' else 'LONG') if side else None,
            score=score,qualifies=score>=75,stop_fraction=str(stop),
            bull_sweep=bullSweep,bear_sweep=bearSweep,bull_mss=bullMSS,bear_mss=bearMSS,
            bull_fvg=bullFVG,bear_fvg=bearFVG,htf=htf,session_bonus=8<=hour<22)
