from pathlib import Path
p=Path('/home/qcmc_admin/frappe-bench/apps/qcmc_logic/qcmc_logic/qcmc_logics/report/collection_report/collection_report.py')
s=p.read_text()
marker='    e=lambda x:escape(str(x)) if x is not None else ""'
assert s.count(marker)==1
s=s[:s.index(marker)]
s=s.replace('from html import escape\n','')
p.write_text(s)
print('CLEANED',len(s))
