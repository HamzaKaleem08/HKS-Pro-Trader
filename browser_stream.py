"""Checkpoint orchestration around the pinned V4 loop, without financial edits.

Only loop scheduling changes: yield after a completed global timestamp, and
restore explicitly typed state before selecting the next chronological candle.
Financial checkpoint data is JSON, never pickle/code. Strategy snapshots are
opaque and restored only in the isolated, trusted-code strategy worker.
"""
import ast
import inspect
import json
import math
import time
from collections import deque
from dataclasses import fields
from decimal import Decimal, localcontext

from backtester import simulation
from backtester.models import Candle, Position, Signal
from backtester.python_definition import PythonSignal
from backtester.portfolio import Account
from backtester.studio_management import ManagedAccount

TYPES = {t.__name__: t for t in (Candle, Position, Signal, PythonSignal, Account, ManagedAccount)}
STATE_NAMES = ('accounts', 'histories', 'pending', 'seen', 'last_bars', 'journal',
               'equity', 'warnings', 'counts', 'position_count')
MAX_CHECKPOINT = 64 * 1024 * 1024

def encode(value):
    if value is None or type(value) in (str, int, bool):
        return value
    if isinstance(value, Decimal):
        return {'@': 'decimal', 'v': str(value)}
    if type(value) is list:
        return [encode(x) for x in value]
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise ValueError('checkpoint dictionary keys must be strings')
        return {'@': 'dict', 'v': [[k, encode(v)] for k, v in value.items()]}
    if type(value) in (tuple, set, deque):
        return {'@': type(value).__name__, 'v': [encode(x) for x in value],
                'maxlen': value.maxlen if isinstance(value, deque) else None}
    name = type(value).__name__
    if TYPES.get(name) is not type(value):
        raise ValueError('unsupported financial checkpoint type: ' + name)
    return {'@': name, 'v': encode(vars(value))}

def decode(value, depth=0):
    if depth > 60:
        raise ValueError('checkpoint nesting limit')
    if value is None or type(value) in (str, int, bool):
        return value
    if type(value) is list:
        return [decode(x, depth + 1) for x in value]
    if type(value) is not dict or set(value) - {'@', 'v', 'maxlen'}:
        raise ValueError('invalid typed checkpoint')
    kind, raw = value.get('@'), value.get('v')
    dec = lambda v: decode(v, depth + 1)
    if kind == 'decimal':
        d = Decimal(raw)
        if not d.is_finite():
            raise ValueError('non-finite checkpoint decimal')
        return d
    if kind == 'dict':
        if any(type(k) is not str for k, _ in raw) or len({k for k, _ in raw}) != len(raw):
            raise ValueError('invalid checkpoint dictionary')
        return {k: dec(v) for k, v in raw}
    if kind in ('tuple', 'set', 'deque'):
        values = [dec(x) for x in raw]
        if kind == 'deque':
            if type(value.get('maxlen')) is not int or not 1 <= value['maxlen'] <= 501:
                raise ValueError('invalid history length')
            return deque(values, maxlen=value['maxlen'])
        return tuple(values) if kind == 'tuple' else set(values)
    cls = TYPES.get(kind)
    if cls is None:
        raise ValueError('unrecognized checkpoint type')
    attrs = dec(raw)
    obj = cls(**{f.name: attrs[f.name] for f in fields(cls)})
    for name, v in attrs.items():
        if name.startswith('__'):
            raise ValueError('unsafe checkpoint attribute')
        object.__setattr__(obj, name, v)
    return obj

def capture(scope, next_ms):
    result = {'schema': 1, 'next_ms': next_ms,
              'state': encode({name: scope[name] for name in STATE_NAMES}),
              'runtime': encode({'previous': scope['strategy'].previous,
                                 'signals': scope['strategy'].signals})}
    raw = json.dumps(result, separators=(',', ':'))
    if len(raw.encode()) > MAX_CHECKPOINT:
        raise ValueError('64 MiB financial checkpoint bound exceeded; no truncated checkpoint')
    return result

def checkpoint_event(scope, next_ms):
    started = time.monotonic()
    snapshot = capture(scope, next_ms)
    return {'kind': 'CHECKPOINT', 'snapshot': snapshot,
            'capture_ms': (time.monotonic() - started) * 1000}

def restore(snapshot, strategy):
    if snapshot.get('schema') != 1 or type(snapshot.get('next_ms')) is not int:
        raise ValueError('unsupported checkpoint schema')
    state = decode(snapshot['state'])
    if set(state) != set(STATE_NAMES):
        raise ValueError('incomplete financial checkpoint')
    runtime = decode(snapshot['runtime'])
    strategy.previous, strategy.signals = runtime['previous'], runtime['signals']
    return state

def make_iterator():
    """Mechanical AST edits are tested against the entire pinned result object."""
    tree = ast.parse(inspect.getsource(simulation._simulate))
    fn = tree.body[0]
    fn.name = '_checkpoint_iterator'
    fn.args.kwonlyargs += [ast.arg(arg=n) for n in ('resume','checkpoint_every','work_steps','yield_seconds')]
    fn.args.kw_defaults += [ast.Constant(None), ast.Constant(120), ast.Constant(240), ast.Constant(1.0)]
    loop = next(n for n in fn.body if isinstance(n, ast.For) and isinstance(n.target, ast.Tuple)
                and [getattr(x, 'id', None) for x in n.target.elts] == ['ts', 'values'])
    before_streams = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == 'streams' for t in n.targets))
    restore_src = '''
if resume is not None:
    _restored = restore(resume, strategy)
    accounts = _restored['accounts']
    histories = _restored['histories']
    pending = _restored['pending']
    seen = _restored['seen']
    last_bars = _restored['last_bars']
    journal = _restored['journal']
    equity = _restored['equity']
    warnings = _restored['warnings']
    counts = _restored['counts']
    position_count = _restored['position_count']
    warmup_start = resume['next_ms']
_completed = 0
_work = 0
_first_checkpoint = resume is not None
_chunk_started = time.monotonic()
'''
    fn.body[before_streams:before_streams] = ast.parse(restore_src).body
    loop.body += ast.parse('''
_completed += 1
_work += len(bars)
_work_boundary = _work >= work_steps or time.monotonic() - _chunk_started >= yield_seconds
if _completed % checkpoint_every == 0 or _work_boundary:
    if _completed % checkpoint_every == 0 or not _first_checkpoint:
        yield checkpoint_event(locals(), end)
        _first_checkpoint = True
    else:
        yield {'kind': 'PROGRESS', 'next_ms': end}
    _work = 0
    started = time.monotonic()
    _chunk_started = started
''').body
    # A generator return retains the original result (including its result hash).
    ast.fix_missing_locations(tree)
    namespace = dict(vars(simulation), checkpoint_event=checkpoint_event, restore=restore)
    exec(compile(tree, '<pinned-v4-checkpoint-scheduling>', 'exec'), namespace)
    return namespace[fn.name]

ITERATE = make_iterator()

def chunks(dataset, strategy, config, resume=None, checkpoint_every=120,
           work_steps=240, yield_seconds=1.0):
    if type(checkpoint_every) is not int or not 1 <= checkpoint_every <= 1440:
        raise ValueError('checkpoint interval must be 1–1440 timestamps')
    if type(work_steps) is not int or not 1 <= work_steps <= 10000:
        raise ValueError('work limit must be 1–10000 symbol-candle steps')
    if type(yield_seconds) not in (int,float) or not math.isfinite(yield_seconds) or not 0 < yield_seconds <= 5:
        raise ValueError('work-time target must be positive and at most five seconds')
    # Keeping this context inside a generator prevents JS scheduling from
    # changing Decimal precision between chunks.
    with localcontext() as context:
        context.prec = 34
        it = ITERATE(dataset, strategy, config, None, resume=resume,
                     checkpoint_every=checkpoint_every,work_steps=work_steps,
                     yield_seconds=yield_seconds)
        while True:
            try:
                yield next(it)
            except StopIteration as done:
                yield {'kind': 'DONE', 'result': done.value}
                return
