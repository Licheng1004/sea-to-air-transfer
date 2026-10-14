"""Audit-friendly inventory allocation and quota-constrained sea-to-air decisions."""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parent

def identifier(value):
    if pd.isna(value):return ''
    text=str(value).strip()
    return text[:-2] if text.endswith('.0') else text

def load_inputs(data_dir):
    paths={name:Path(data_dir)/name for name in ['Open PO.xlsx','Open SO.xlsx','Material List.xlsx','Quota.xlsx']}
    frames={name:pd.read_excel(path,sheet_name='Sheet1') for name,path in paths.items()}
    return frames

def prepare(frames,as_of):
    po_raw=frames['Open PO.xlsx'];so=frames['Open SO.xlsx'].copy();mt=frames['Material List.xlsx'].copy()
    po=po_raw.drop_duplicates().copy()
    mt['MATERIAL']=mt.MATERIAL.astype(str)
    if mt.MATERIAL.duplicated().any():raise ValueError('Material master must have unique MATERIAL values.')
    mt=mt.set_index('MATERIAL')
    po['po_key']=po.PURCH_ORDER_NUMBER.map(identifier)+'/'+po.PURCH_ORDER_ITEM.map(identifier)
    po['MATERIAL']=po.MATERIAL.astype(str)
    po['due']=pd.to_datetime(po.DUEDATE,errors='coerce')
    po['quantity']=pd.to_numeric(po.OPEN_QTY,errors='coerce')
    po=po[(po.PO_LA==0)&(po.quantity>0)].copy()
    ambiguous=po.po_key.duplicated(keep=False)
    quarantine=po[ambiguous].copy()
    po=po[~ambiguous].copy()
    rejected=[];supplies=[]
    for row in po.to_dict('records'):
        material=row['MATERIAL']
        if pd.isna(row['due']):rejected.append({'po_key':row['po_key'],'reason':'invalid due date'});continue
        meta=mt.loc[material] if material in mt.index else {}
        unit=str(meta.get('WEIGHT_UNIT','')).strip().upper()
        weight=pd.to_numeric(meta.get('GROSS_WEIGHT',np.nan),errors='coerce')
        weight_g=float(weight)*({'G':1,'KG':1000}.get(unit,np.nan))
        supplies.append({'po_key':row['po_key'],'material':material,'quantity':float(row['quantity']),
            'remaining':float(row['quantity']),'sea_arrival':max(as_of,row['due']), 'arrival':max(as_of,row['due']),
            'method':str(row['PURCHASING_GROUP']).strip(),'country':str(row['VENDOR_COUNTRY']).strip(),
            'policy':str(row['STOCKING_POLICY']).strip(),'entity':str(meta.get('ENTITY','')),
            'unit_weight_g':weight_g,'transferred':False})
    so['MATERIAL']=so.MATERIAL.astype(str)
    so['so_key']=so.SALES_ORDER_NUMBER.map(identifier)+'/'+so.SALES_ORDER_ITEM.map(identifier)
    if so.so_key.duplicated().any():raise ValueError('Sales order keys are not unique.')
    so['po_key']=so.PURCH_ORDER_NUMBER.map(identifier)+'/'+so.PURCH_ORDER_ITEM.map(identifier)
    so['deadline']=pd.to_datetime(so.CRD_DATE,errors='coerce')
    so['quantity']=pd.to_numeric(so.OPEN_SO_W_O_DEL,errors='coerce')
    invalid=so[so.deadline.isna()|so.quantity.isna()|(so.quantity<=0)].copy()
    so=so[so.deadline.notna()&so.quantity.notna()&(so.quantity>0)].copy()
    priorities=pd.to_numeric(so.DELIVERY_PRIORITY.replace('Others',2),errors='coerce').fillna(2)
    priorities.loc[so.VIP_BU.fillna('').astype(str).str.strip().ne('')&~priorities.isin([1,4])]=3
    priorities.loc[(so.deadline<as_of)&(priorities!=1)]=5
    priorities.loc[priorities==1]=6
    so['priority']=priorities.astype(int)
    so['kind']='sales_order'
    demands=so[['so_key','po_key','MATERIAL','deadline','quantity','priority','kind']].to_dict('records')
    inventory={m:max(0,float(pd.to_numeric(row.get('UU_STOCK',0),errors='coerce') or 0)) for m,row in mt.iterrows()}
    inventory={m:(v if np.isfinite(v) else 0) for m,v in inventory.items()}
    # Forecast buffer is created once per material, after real sales orders.
    for material in sorted(so.loc[so.po_key=='/','MATERIAL'].unique()):
        if material not in mt.index:continue
        row=mt.loc[material]
        lead=pd.to_numeric(row.get('PLANNED_DELIV_TIME'),errors='coerce')
        fcst=pd.to_numeric(row.get('M_1_FORECAST'),errors='coerce')
        if pd.notna(lead) and pd.notna(fcst) and lead>0 and fcst>0:
            demands.append({'so_key':f'BUFFER/{material}','po_key':'/','MATERIAL':material,'deadline':as_of+pd.Timedelta(days=float(lead)),
                            'quantity':float(np.ceil(lead*fcst/30)),'priority':0,'kind':'forecast_buffer'})
    quota=frames['Quota.xlsx'].set_index(frames['Quota.xlsx'].columns[0])
    month=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][as_of.month-1]
    budget={str(entity):float(re.sub(r'[^0-9.]','',str(row[month])))*1000 for entity,row in quota.iterrows()}
    profile={'input_po_rows':len(po_raw),'exact_duplicate_po_rows_removed':int(po_raw.duplicated().sum()),
             'ambiguous_po_rows_quarantined':len(quarantine),'po_rows_rejected':len(rejected),'usable_po_lines':len(supplies),
             'input_so_rows':len(frames['Open SO.xlsx']),'invalid_or_nonpositive_so_rows':len(invalid),'sales_orders':len(so),
             'buffer_demands':sum(d['kind']=='forecast_buffer' for d in demands),'quota_month':month}
    return supplies,demands,inventory,budget,profile,quarantine,pd.DataFrame(rejected),invalid

def allocate(frames,as_of='2024-11-04',air_days=7,policy='smallest_first',allow_air=True):
    as_of=pd.Timestamp(as_of).normalize()
    supplies,demands,stock,budget,profile,quarantine,rejected,invalid=prepare(frames,as_of)
    original_stock=stock.copy();original_budget=budget.copy()
    by_material=defaultdict(list)
    for supply in supplies:by_material[supply['material']].append(supply)
    allocations=[];transfers=[];demand_results=[]
    demands.sort(key=lambda x:(-x['priority'],x['deadline'],x['so_key']))
    for demand in demands:
        material=demand['MATERIAL'];remaining=demand['quantity'];deadline=demand['deadline']
        timely=0.;late=0.
        def record(source,key,qty,arrival,air=False):
            nonlocal remaining,timely,late
            remaining-=qty
            if arrival<=deadline:timely+=qty
            else:late+=qty
            allocations.append({'demand_key':demand['so_key'],'kind':demand['kind'],'priority':demand['priority'],
                'material':material,'source':source,'po_key':key,'quantity':qty,'arrival':str(arrival.date()),
                'deadline':str(deadline.date()),'on_time':arrival<=deadline,'expedited':air})
        used=min(remaining,stock.get(material,0))
        if used>0:
            stock[material]-=used;record('inventory','',used,as_of)
        candidates=[s for s in by_material[material] if s['remaining']>0 and
            ((demand['po_key']!='/' and s['po_key']==demand['po_key']) or
             (demand['po_key']=='/' and s['policy'] in ('MTS','FMTS')))]
        cutoff=max(as_of,deadline)
        for supply in sorted(candidates,key=lambda s:(s['arrival'],s['po_key'])):
            if remaining<=1e-9:break
            if supply['arrival']<=cutoff:
                used=min(remaining,supply['remaining']);supply['remaining']-=used
                record('purchase_order',supply['po_key'],used,supply['arrival'],supply['transferred'])
        air_arrival=as_of+pd.Timedelta(days=air_days)
        possible=[s for s in candidates if s['remaining']>0 and not s['transferred'] and s['method']=='O02'
                  and s['country']!='SG' and s['sea_arrival']>max(air_arrival,cutoff)
                  and np.isfinite(s['unit_weight_g']) and s['unit_weight_g']>0 and s['entity'] in budget]
        if policy=='smallest_first':possible.sort(key=lambda s:(s['quantity'],s['sea_arrival'],s['po_key']))
        elif policy=='earliest_due':possible.sort(key=lambda s:(s['sea_arrival'],s['quantity'],s['po_key']))
        elif policy=='closest_quantity':possible.sort(key=lambda s:(abs(s['remaining']-remaining),s['quantity'],s['po_key']))
        else:raise ValueError('Unknown candidate policy')
        if allow_air:
            for supply in possible:
                if remaining<=1e-9:break
                weight=supply['quantity']*supply['unit_weight_g']
                if weight>budget[supply['entity']]+1e-9:continue
                budget[supply['entity']]-=weight;supply['transferred']=True;supply['arrival']=air_arrival
                transfers.append({'po_key':supply['po_key'],'material':material,'entity':supply['entity'],
                    'country':supply['country'],'original_method':supply['method'],'quantity':supply['quantity'],
                    'weight_kg':weight/1000,'sea_arrival':str(supply['sea_arrival'].date()),'air_arrival':str(air_arrival.date())})
                used=min(remaining,supply['remaining']);supply['remaining']-=used
                record('purchase_order',supply['po_key'],used,supply['arrival'],True)
        demand_results.append({'demand_key':demand['so_key'],'material':material,'kind':demand['kind'],
            'priority':demand['priority'],'deadline':str(deadline.date()),'requested':demand['quantity'],
            'on_time_quantity':timely,'late_expedited_or_available_quantity':late,'unallocated':max(0,remaining)})
    result=pd.DataFrame(demand_results);transfer_frame=pd.DataFrame(transfers)
    quota=pd.DataFrame([{'entity':e,'initial_kg':original_budget[e]/1000,'used_kg':(original_budget[e]-budget[e])/1000,
                        'remaining_kg':budget[e]/1000} for e in budget])
    sales=result[result.kind=='sales_order']
    fulfilled=sales[sales.unallocated<1e-8]
    on_time=sales[sales.on_time_quantity>=sales.requested-1e-8]
    score=[int((fulfilled.priority==priority).sum()) for priority in [6,5,4,3,2]]
    checks={'quota_nonnegative':all(v>=-1e-8 for v in budget.values()),'stock_nonnegative':all(v>=-1e-8 for v in stock.values()),
            'po_supply_conserved':all(-1e-8<=s['remaining']<=s['quantity']+1e-8 for s in supplies),
            'unique_transfer_keys':len(transfers)==len({t['po_key'] for t in transfers}),
            'candidate_method_and_country':all(t['original_method']=='O02' and t['country']!='SG' for t in transfers),
            'demand_conserved':bool(np.allclose(result.requested,result.on_time_quantity+result.late_expedited_or_available_quantity+result.unallocated))}
    if not all(checks.values()):raise AssertionError(checks)
    summary={'as_of':str(as_of.date()),'air_transit_days':air_days,'policy':policy,'allow_air':allow_air,
        'fully_allocated_sales_orders':len(fulfilled),'fully_on_time_sales_orders':len(on_time),'sales_orders':len(sales),
        'priority_fulfillment_score':score,'transferred_po_lines':len(transfers),'air_weight_kg':float(quota.used_kg.sum()),
        'checks':checks,'input_profile':profile,'warning':'Greedy decision support, not a proof of global optimality. Overdue orders cannot become on-time retroactively.'}
    return summary,{'demand_outcomes':result,'allocations':pd.DataFrame(allocations),'transfers':transfer_frame,
                   'quota_remaining':quota,'quarantined_po_rows':quarantine,'rejected_po_rows':rejected,'invalid_so_rows':invalid}

def run(data_dir=None,output_dir=None,as_of=None):
    config=json.loads((ROOT/'config.json').read_text())
    if as_of:config['as_of']=as_of
    summary,tables=allocate(load_inputs(data_dir or ROOT/'data'),**config)
    output=Path(output_dir or ROOT/'results');output.mkdir(parents=True,exist_ok=True)
    for name,table in tables.items():table.to_csv(output/f'{name}.csv',index=False)
    (output/'run_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    return summary,tables

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path);parser.add_argument('--output-dir',type=Path);parser.add_argument('--as-of')
    args=parser.parse_args();summary,_=run(args.data_dir,args.output_dir,args.as_of);print(json.dumps(summary,indent=2))
