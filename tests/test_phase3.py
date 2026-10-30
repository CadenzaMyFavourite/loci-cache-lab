import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from phase3_analyze import quantiles,summary,paired_bootstrap

def row(i,value,success=True):
    return {'request_id':i,'phase':'measured','success':success,'ttft_ms':value,
        'scheduled_ttft_ms':value,'http_ttft_ms':value,'queue_ms':0.,'arrival_lateness_ms':0.,
        'timings':{'prompt_n':20,'cache_n':80},'probe_pass':True,
        'http_dispatch_us':i*1000000,'eof_us':i*1000000+value*1000,'done_us':i*1000000+value*1000}

class TailTests(unittest.TestCase):
    def test_linear_quantiles_and_failure_denominators(self):
        self.assertEqual(quantiles([100,300,500,600])['p95'],585.)
        self.assertEqual(quantiles([100,300,500,600])['p99'],597.)
        r=summary([row(i,t) for i,t in enumerate([100,300,500,600])]+[row(4,0,False)])
        self.assertEqual(r['failures'],1)
        self.assertEqual(r['exceedance_success_fraction']['500'],.25)
        self.assertEqual(r['exceedance_attempt_bounds']['500'],[.2,.4])
    def test_identical_trial_pairs_have_zero_bootstrap_delta(self):
        a={0:[row(0,10),row(1,20)],1:[row(0,500),row(1,800)]}
        result=paired_bootstrap(a,a,100)
        self.assertEqual(result['ttft_ms']['p95']['delta_95_ms'],[0.,0.])
        self.assertEqual(result['over_500ms']['delta_95_percentage_points'],[0.,0.])

if __name__=='__main__':unittest.main()
