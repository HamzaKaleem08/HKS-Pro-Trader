"""Separate position lifecycle statistics from partial-exit segment statistics."""
from collections import defaultdict
from decimal import Decimal,localcontext

from .common import primitives


def position_performance(result):
    with localcontext() as ctx:
        ctx.prec=34
        groups=defaultdict(lambda:Decimal(0))
        open_ids={p['trade_id'] for p in result['open_positions']}
        for t in result['trades']:
            groups[t.get('position_id',t['trade_id'])]+=Decimal(t['net_pnl'])
        closed={k:v for k,v in groups.items() if k not in open_ids}
        wins=sum(v>0 for v in closed.values());losses=sum(v<0 for v in closed.values());count=len(closed)
        return primitives({'closed_positions':count,'open_positions':len(open_ids),'closed_exit_segments':len(result['trades']),
                           'wins':wins,'losses':losses,'breakeven':count-wins-losses,
                           'win_rate_pct':Decimal(wins)*100/count if count else None,
                           'net_from_fully_closed_positions':sum(closed.values(),Decimal(0)),
                           'realized_net_from_still_open_positions':sum((v for k,v in groups.items() if k in open_ids),Decimal(0)),
                           'scope':'Complete entry-to-final-exit lifecycles; partial segment outcomes are NOT independent trade wins'})
