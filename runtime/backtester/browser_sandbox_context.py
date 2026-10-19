"""Browser-only API extension. No strategies or financial rules execute here.

The broker supplies verified completed UTC aggregates; this API independently
checks their causal boundaries before exposing immutable Candle tuples.
The preserved native Context and Decimal financial kernel remain unchanged.
"""
from decimal import Decimal
from sandbox_api import Context as BaseContext, Candle

CONTRACT = 'HKS_BROWSER_COMPLETED_CONTEXT/2'
PERIODS = {'15m': 900000, '1h': 3600000}


def completed_context(row, asof):
    supplied = row.get('contexts', {})
    if type(supplied) is not dict or len(supplied) > 2:
        raise ValueError('Bounded completed contexts required')
    result = {}
    for timeframe, bars in supplied.items():
        if timeframe not in PERIODS or type(bars) is not list or not 2 <= len(bars) <= 64:
            raise ValueError('Invalid completed context request')
        period = PERIODS[timeframe]
        parsed = []
        for b in bars:
            t = b['open_ms']
            if type(t) is not int or t % period or b['interval_ms'] != period or t + period > asof:
                raise ValueError('Incomplete/future context refused')
            c = Candle(row['symbol'], t, period,
                       *(Decimal(b[k]) for k in ['open', 'high', 'low', 'close', 'volume']))
            if (not all(x.is_finite() for x in c[3:]) or min(c.open, c.high, c.low, c.close) <= 0
                    or c.volume < 0 or not c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high):
                raise ValueError('Invalid context OHLCV')
            if parsed and c.open_ms != parsed[-1].open_ms + period:
                raise ValueError('Context gap/duplicate refused')
            parsed.append(c)
        if parsed[-1].open_ms + period != asof // period * period:
            raise ValueError('Stale completed context refused')
        result[timeframe] = tuple(parsed)
    return result


class Context(BaseContext):
    context_contract = CONTRACT
    context_timeframes = tuple(PERIODS)

    def __init__(self, row, history, state):
        super().__init__(row, history, state)
        self._completed_context = completed_context(row, self.timestamp_ms)
        self.last_exit = row.get('last_exit')
        if self.last_exit is not None:
            if type(self.last_exit) is not dict or set(self.last_exit) != {
                    'exit_ms', 'fill_window_start_ms', 'fill_window_end_ms', 'exit_reason'}:
                raise ValueError('Invalid last-exit evidence')
            if any(type(self.last_exit[k]) is not int for k in [
                    'exit_ms', 'fill_window_start_ms', 'fill_window_end_ms']):
                raise ValueError('Invalid last-exit timestamps')
            if (not 0 <= self.last_exit['fill_window_start_ms'] <= self.last_exit['fill_window_end_ms'] <= self.timestamp_ms
                    or self.last_exit['exit_ms'] > self.timestamp_ms):
                raise ValueError('Future last-exit evidence refused')

    def candles(self, timeframe):
        """Read-only, completed candles in chronological order; never current bars."""
        if timeframe not in self._completed_context:
            raise ValueError('Declare CONTEXT_TIMEFRAMES = {"15m":50,"1h":21}; completed pre-window data is required')
        return self._completed_context[timeframe]
