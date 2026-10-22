"""Runtime rejects tampered active weights and a pending promotion journal."""
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import batch_contract as batch

class BatchContractTests(unittest.TestCase):
    def test_weight_is_checked_again_after_replacement_and_missing_members_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=root/'weight.pkl';p.write_bytes(b'original')
            c={'training_version':4,'engine_contract':4,'models':[{'name':p.name,'cutoff':'2025-09-01','sha256':hashlib.sha256(p.read_bytes()).hexdigest()}]}
            c['batch_id']=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            context=root/'active-batch.json';context.write_text(json.dumps(c),encoding='utf8')
            with patch.object(batch,'ROOT',root),patch.object(batch,'context_path',return_value=context):
                self.assertEqual(batch.weight_identity(p,'2025-09-01')[0],c['batch_id'])
                with self.assertRaisesRegex(ValueError,'不屬於'):batch.weight_identity(p,'2025-10-01')
                p.write_bytes(b'tampered content')
                with self.assertRaisesRegex(ValueError,'雜湊'):batch.weight_identity(p,'2025-09-01')
    def test_pending_journal_blocks_reads_until_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'output').mkdir();(root/'output/promotion-journal.json').write_text('{}')
            with patch.object(batch,'ROOT',root),self.assertRaisesRegex(RuntimeError,'恢復'):batch.ensure_available()

if __name__=='__main__':unittest.main()
