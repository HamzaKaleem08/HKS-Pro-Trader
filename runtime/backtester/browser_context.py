"""Bounded browser-only completed-timeframe context. No strategy code executes here.

The original financial loop, sizing, fills and account methods are unchanged.
Only declared, fully closed UTC aggregates cross to the isolated Python worker.
"""
import ast
from bisect import bisect_right
from decimal import Decimal, localcontext

from .errors import ValidationError
from .models import Candle

CONTRACT = 'HKS_BROWSER_COMPLETED_CONTEXT/1'
PERIODS = {'15m': 900000, '1h': 3600000}
MINUTE = 60000


def requirements(definition, warmup_bars):
    tree = ast.parse(definition['code'])
    declared = []
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == 'CONTEXT_TIMEFRAMES' for t in targets):
                declared.append(node.value)
    if not declared:
        return {}, warmup_bars
    if len(declared) != 1:
        raise ValidationError('Declare CONTEXT_TIMEFRAMES once as a literal dictionary')
    node = declared[0]
    if not isinstance(node, ast.Dict) or not 1 <= len(node.keys) <= 2:
        raise ValidationError('CONTEXT_TIMEFRAMES supports one or two literal 15m/1h requests')
    result = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant) or type(key.value) is not str or key.value not in PERIODS:
            raise ValidationError('Completed context supports only 15m and 1h from verified 1m input')
        if key.value in result or not isinstance(value, ast.Constant) or type(value.value) is not int or not 2 <= value.value <= 64:
            raise ValidationError('Each declared timeframe needs a distinct count from 2 to 64')
        result[key.value] = value.value
    # One extra bucket covers an arbitrary minute-aligned start, including a
    # partially supplied first UTC hour. Evaluation dates are never shortened.
    needed = max([warmup_bars] + [(count+1)*(PERIODS[tf]//MINUTE) for tf, count in result.items()])
    return result, needed


def aggregate(rows, timeframe):
    period = PERIODS[timeframe]
    required = period//MINUTE
    result = [];group = [];bucket = None
    with localcontext() as context:
        context.prec = 34
        for bar in rows:
            start = bar.open_ms//period*period
            if start != bucket:
                group = [];bucket = start
            group.append(bar)
            if (len(group) == required and group[0].open_ms == start and
                    bar.end_ms == start+period and
                    all(b.interval_ms == MINUTE and b.open_ms == start+i*MINUTE for i, b in enumerate(group))):
                result.append(Candle(bar.symbol, start, period, group[0].open,
                    max(b.high for b in group), min(b.low for b in group), bar.close,
                    sum((b.volume for b in group), Decimal(0))))
    return tuple(result)


class CompletedContext:
    def __init__(self, dataset, requested, input_warmup_bars, start_ms):
        if dataset.interval != '1m':
            raise ValidationError('Completed multi-timeframe context requires verified 1m input')
        self.requested = requested;self.series = {};self.ends = {}
        for symbol, rows in dataset.candles.items():
            if not rows or rows[0].open_ms > start_ms-input_warmup_bars*MINUTE:
                raise ValidationError(symbol+': missing declared multi-timeframe pre-window warm-up; no delayed or shortened test')
            for timeframe in requested:
                bars = aggregate(rows, timeframe);key = symbol, timeframe
                self.series[key] = bars;self.ends[key] = tuple(b.end_ms for b in bars)
            self.at(symbol, start_ms)  # Refuse before any simulated entry or fill.

    def at(self, symbol, asof_ms):
        result = {}
        for timeframe, count in self.requested.items():
            key = symbol, timeframe
            end = bisect_right(self.ends[key], asof_ms)
            bars = self.series[key][max(0, end-count):end]
            period = PERIODS[timeframe]
            if (len(bars) != count or bars[-1].end_ms > asof_ms or
                    bars[-1].end_ms != asof_ms//period*period or
                    any(b.open_ms != bars[0].open_ms+i*period for i, b in enumerate(bars))):
                raise ValidationError(symbol+': insufficient continuous completed '+timeframe+' context at decision time')
            result[timeframe] = [{'open_ms': b.open_ms, 'interval_ms': b.interval_ms,
                **{k: str(getattr(b, k)) for k in ('open', 'high', 'low', 'close', 'volume')}} for b in bars]
        return result
