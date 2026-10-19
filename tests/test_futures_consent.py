"""Synthetic Futures consent regressions, no execution of host strategy code."""
from dataclasses import replace
import json
import unittest

from test_checkpoint import dataset, runtime, config, chunks
from backtester.config import RunConfig
from backtester.errors import ValidationError
from backtester.simulation import simulate


class FuturesConsentTests(unittest.TestCase):
    def test_json_true_reaches_python_and_shared_and_individual_results(self):
        ds = replace(dataset(), market='USDT_LINEAR_PERPETUAL')
        for mode in ('shared', 'individual'):
            cfg = RunConfig.from_dict(json.loads(json.dumps({
                'start_ms': config().start_ms, 'end_ms': config().end_ms,
                'mode': mode, 'allow_uncertified_futures': True})))
            result = list(chunks(ds, runtime(), cfg, checkpoint_every=2))[-1]['result']
            self.assertIs(result['config']['allow_uncertified_futures'], True)
            self.assertEqual(result, simulate(ds, runtime(), cfg))

    def test_missing_or_false_reaches_unchanged_python_safety_gate(self):
        ds = replace(dataset(), market='USDT_LINEAR_PERPETUAL')
        for raw in ({}, {'allow_uncertified_futures': False}):
            cfg = RunConfig.from_dict({'start_ms': config().start_ms,
                                      'end_ms': config().end_ms, **raw})
            with self.assertRaisesRegex(ValidationError, 'allow_uncertified_futures=true required'):
                list(chunks(ds, runtime(), cfg))

    def test_checkpoint_restart_keeps_consent_and_exact_financial_result(self):
        ds = replace(dataset(), market='USDT_LINEAR_PERPETUAL')
        for mode in ('individual', 'shared'):
            cfg = replace(config(mode), allow_uncertified_futures=True)
            full = list(chunks(ds, runtime(), cfg, checkpoint_every=2))
            snapshot = json.loads(json.dumps(full[1]['snapshot']))
            resumed = list(chunks(ds, runtime(), cfg, resume=snapshot, checkpoint_every=3))[-1]['result']
            self.assertEqual(resumed, full[-1]['result'])
            self.assertIs(resumed['config']['allow_uncertified_futures'], True)

    def test_checkpoint_cannot_bypass_consent_if_resume_config_is_false(self):
        ds = replace(dataset(), market='USDT_LINEAR_PERPETUAL')
        cfg = replace(config(), allow_uncertified_futures=True)
        snapshot = list(chunks(ds, runtime(), cfg, checkpoint_every=2))[0]['snapshot']
        with self.assertRaisesRegex(ValidationError, 'allow_uncertified_futures=true required'):
            list(chunks(ds, runtime(), replace(cfg, allow_uncertified_futures=False), resume=snapshot))

    def test_truthy_non_boolean_consent_rejected_by_python_config(self):
        for value in ('true', 1, {}, None):
            with self.assertRaisesRegex(ValidationError, 'explicit boolean'):
                RunConfig.from_dict({'start_ms': config().start_ms, 'end_ms': config().end_ms,
                                     'allow_uncertified_futures': value})


if __name__ == '__main__':
    unittest.main()
