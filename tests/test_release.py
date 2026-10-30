import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from release_evidence import portable,ROOT
from demo import summarize,compare

class ReleaseTests(unittest.TestCase):
    def test_portable_copy_normalizes_nested_scope_without_changing_numbers(self):
        original={'scope':json.dumps({'model':str(ROOT/'models/model.gguf')}),'ttft_ms':300.2,'timings':{'prompt_n':2044,'cache_n':4}}
        result=portable(original)
        self.assertIn('<WORKSPACE>',json.loads(result['scope'])['model'])
        self.assertNotIn(str(ROOT),result['scope'])
        self.assertEqual(result['timings'],original['timings'])
        self.assertEqual(result['ttft_ms'],original['ttft_ms'])
        self.assertIn(str(ROOT),json.loads(original['scope'])['model'])
    def test_demo_keeps_failures_out_of_latency_quantiles_and_counts_warmup(self):
        good={'phase':'measured','success':True,'ttft_ms':10.,'timings':{'prompt_n':4,'cache_n':16}}
        bad={'phase':'measured','success':False,'ttft_ms':None}
        r=summarize([good,bad,{'phase':'warmup','success':False}])
        self.assertEqual(r['attempts'],2);self.assertEqual(r['failures'],1)
        self.assertEqual(r['warmup_failures'],1);self.assertEqual(r['median_ttft_ms'],10.)
    def test_demo_refuses_existing_output_before_hardware_access(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'fresh'):
                compare(SimpleNamespace(out=folder))

if __name__=='__main__':unittest.main()
