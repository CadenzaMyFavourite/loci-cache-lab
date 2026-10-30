import sys
import pathlib
import tempfile
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"scripts"))
from concurrency_analyze import parse_log,correlate
from concurrency_report import activity

class LogEvidenceTests(unittest.TestCase):
    def test_overlap_groups_simultaneous_release_and_dispatch(self):
        result=activity([(0,2),(1,3),(2,4)])
        self.assertEqual(result['max_active'],2)
        self.assertEqual(result['mean_active'],1.5)
        self.assertEqual(result['fraction_wall_time_with_two_or_more'],.5)
    def test_decode_gate_is_not_a_slot_unavailable_event(self):
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/"server.log"
            path.write_text("0.00.001.000 D que post: new task, id = 3/1, front = 0\n0.00.002.000 D srv process_sing: decoding, decline task, id_task = 3\n0.00.010.000 I slot launch_slot_: id  0 | task 3 | processing task, is_child = 0\n",encoding='utf-8')
            tasks,events=parse_log(path)
            self.assertEqual(tasks[3]['posted_ms'],1)
            self.assertEqual(tasks[3]['launched_ms'],10)
            self.assertEqual(events[0]['kind'],'decode_gate')
    def test_rejects_ambiguous_or_mismatched_correlations(self):
        row={'success':True,'actual_slot':0,'headers_us':10,'request_id':0,'timings':{'prompt_n':1},'output_tokens':[3]}
        tasks={7:{'slot':0,'launched_ms':1,'released_ms':2,'evaluated':1,'token_ids':[9]}}
        joined,errors=correlate([row],tasks)
        self.assertEqual(joined,[])
        self.assertTrue(errors)
    def test_selection_timestamp_does_not_use_old_slot_task_id(self):
        with tempfile.TemporaryDirectory() as folder:
            path=pathlib.Path(folder)/'server.log'
            path.write_text('0.00.010.000 I slot release: id  1 | task 4 | stop processing: n_tokens = 107\n0.00.011.000 I slot get_availabl: id  0 | task -1 | selected slot by id (0)\n0.00.012.000 I slot launch_slot_: id  0 | task 7 | processing task, is_child = 0\n',encoding='utf-8')
            tasks,_=parse_log(path)
            self.assertEqual(tasks[7]['selected_ms'],11)
            self.assertLess(tasks[4]['released_ms'],tasks[7]['selected_ms'])
            self.assertEqual(tasks[7]['slot'],0)

if __name__=='__main__':unittest.main()
