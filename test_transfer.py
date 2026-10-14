"""Regression checks for allocation risks found in the legacy notebooks."""
import unittest
import pandas as pd
import transfer

class AllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames=transfer.load_inputs(transfer.ROOT/'data')
        cls.summary,cls.tables=transfer.allocate(cls.frames,policy='closest_quantity')

    def test_independent_quota_reconciliation(self):
        selected=self.tables['transfers']
        used=selected.groupby('entity').weight_kg.sum()
        quota=self.tables['quota_remaining'].set_index('entity')
        for entity,row in quota.iterrows():
            self.assertAlmostEqual(row.initial_kg-row.remaining_kg,float(used.get(entity,0)),places=7)

    def test_physical_purchase_line_used_only_once(self):
        supplies,*_=transfer.prepare(self.frames,pd.Timestamp('2024-11-04'))
        available={s['po_key']:s['quantity'] for s in supplies}
        allocated=self.tables['allocations'].query("source == 'purchase_order'").groupby('po_key').quantity.sum()
        for key,quantity in allocated.items():self.assertLessEqual(quantity,available[key]+1e-8)
        self.assertFalse(self.tables['transfers'].po_key.duplicated().any())

    def test_restricted_origin_never_transferred(self):
        self.assertTrue((self.tables['transfers'].country!='SG').all())
        self.assertTrue((self.tables['transfers'].original_method=='O02').all())

    def test_inventory_is_consumed_at_most_once(self):
        _,_,stock,*_=transfer.prepare(self.frames,pd.Timestamp('2024-11-04'))
        used=self.tables['allocations'].query("source == 'inventory'").groupby('material').quantity.sum()
        for material,quantity in used.items():self.assertLessEqual(quantity,stock[material]+1e-8)

    def test_linked_orders_use_only_their_purchase_order(self):
        _,demands,*_=transfer.prepare(self.frames,pd.Timestamp('2024-11-04'))
        linked={d['so_key']:d['po_key'] for d in demands if d['po_key']!='/'}
        records=self.tables['allocations'].query("source == 'purchase_order'")
        for row in records.itertuples():
            if row.demand_key in linked:self.assertEqual(row.po_key,linked[row.demand_key])

    def test_ambiguous_schedule_is_quarantined(self):
        self.assertEqual(len(self.tables['quarantined_po_rows']),2)
        self.assertNotIn('4512723718/1',set(self.tables['transfers'].po_key))

    def test_overdue_orders_cannot_be_on_time(self):
        result=self.tables['demand_outcomes']
        overdue=result[pd.to_datetime(result.deadline)<pd.Timestamp('2024-11-04')]
        self.assertTrue((overdue.on_time_quantity==0).all())

    def test_no_air_does_not_spend_quota(self):
        summary,tables=transfer.allocate(self.frames,allow_air=False)
        self.assertEqual(summary['air_weight_kg'],0)
        self.assertEqual(len(tables['transfers']),0)

if __name__=='__main__':unittest.main()
