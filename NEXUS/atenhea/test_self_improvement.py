import io
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from self_improvement import (build_snapshot, digest, prepare_training,
                              proposal_context, request_proposal, validate_separation)
from interaction_learning import _personal_examples


class SelfImprovementTests(unittest.TestCase):
    def test_sources_are_embedded_and_checksummed(self):
        snapshot = build_snapshot()
        self.assertEqual(snapshot['execution_policy'], 'documentation_only_never_exec')
        self.assertGreater(len(snapshot['sources']), 5)
        for source in snapshot['sources']:
            self.assertEqual(digest(source['content']), source['sha256'])
            self.assertNotIn('models/', source['path'])
        self.assertIn('No inventes', proposal_context(snapshot))

    def test_only_verified_replay_and_no_heldout_overlap(self):
        memory = Mock()
        memory.call.return_value = [
            {'prompt': 'No revisado', 'completion': 'Incorrecto', 'verified': False},
            {'prompt': 'Pregunta aparte', 'completion': 'Revisado', 'verified': True, 'area': 'code'},
            {'prompt': '  PRUEBA   separada ', 'completion': 'Filtrada', 'verified': True},
            {'prompt': 'Pregunta aparte', 'completion': 'Duplicado', 'verified': True},
        ]
        train = [{'prompt': 'Entrenamiento', 'completion': 'Respuesta'}]
        heldout = [{'prompt': 'Prueba separada', 'completion': 'Objetivo'}]
        rows, snapshot = prepare_training(train, heldout, memory, replay_limit=2)
        replay = [r for r in rows if r.get('source') == 'chl_verified_replay']
        self.assertEqual(len(replay), 1)
        self.assertEqual(replay[0]['completion'], 'Duplicado')  # newest verified correction wins
        self.assertEqual(snapshot['training_context']['verified_replay_examples'], 1)
        self.assertEqual(train, [{'prompt': 'Entrenamiento', 'completion': 'Respuesta'}])

    def test_specialization_and_disabled_replay(self):
        memory = Mock()
        rows, snapshot = prepare_training([{'prompt': 'Datos', 'completion': 'Objetivo'}], [],
                                           memory, replay_limit=0, specialization='world')
        memory.call.assert_not_called()
        self.assertEqual(len(rows), 2)
        self.assertIn('mundo', rows[-1]['prompt'])
        self.assertEqual(snapshot['training_context']['specialization'], 'world')

    def test_leakage_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'overlap'):
            validate_separation([{'prompt': 'MI pregunta'}], [{'prompt': ' mi   pregunta '}])
        train, heldout = _personal_examples({'name': 'David'})
        validate_separation(train, heldout)

    def test_proposals_are_unverified_and_not_executed(self):
        response = {'model': 'local', 'choices': [{'finish_reason': 'stop',
                    'message': {'content': '{"hypothesis":"measure first"}'}}]}
        with patch('self_improvement.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
            proposal = request_proposal('Source code')
        self.assertFalse(proposal['verified'])
        self.assertFalse(proposal['applied_to_optimizer'])

    def test_partial_proposals_rejected(self):
        response = {'choices': [{'finish_reason': 'length', 'message': {'content': 'Partial'}}]}
        with patch('self_improvement.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(response).encode())):
            with self.assertRaisesRegex(ValueError, 'completed'):
                request_proposal('code')


class RSILoopTests(unittest.TestCase):
    def test_rounds_use_only_accepted_predecessor_and_keep_original(self):
        from rsi_loop import run_loop
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / 'base.nram'
            bundle.write_bytes(b'original')
            inputs = []
            def train(candidate, index):
                inputs.append(candidate.read_bytes())
                candidate.write_bytes(f'candidate-{index}'.encode())
                return {'accepted': index == 1, 'finite_metrics': True,
                        'validation_nll_after': 1.0}
            report = run_loop(bundle, root / 'run', 3, train)
            self.assertEqual(inputs, [b'original', b'candidate-1'])
            self.assertEqual(bundle.read_bytes(), b'original')
            self.assertTrue(report['accepted_candidate'].endswith('candidate-1.nram'))
            self.assertFalse(report['runtime_promoted'])

    def test_nonfinite_candidate_stops_recursion(self):
        from rsi_loop import run_loop
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / 'base.nram'
            bundle.write_bytes(b'original')
            runner = Mock(return_value={'accepted': True, 'finite_metrics': True,
                                        'validation_nll_after': float('nan')})
            result = run_loop(bundle, root / 'run', 3, runner)
            self.assertIsNone(result['accepted_candidate'])
            self.assertEqual(runner.call_count, 1)
            with self.assertRaises(ValueError):
                run_loop(bundle, root / 'other', 4, runner)
