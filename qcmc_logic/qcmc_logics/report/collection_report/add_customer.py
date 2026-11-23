from pathlib import Path
p=Path('apps/qcmc_logic/qcmc_logic/qcmc_logics/report/collection_report/print_layout.py')
s=p.read_text()
s=s.replace("' class=\"num\"' if field in monetary else ''","' class=\"num\"' if field in monetary else (' class=\"customer\"' if field == \"customer_name\" else '')")
s=s.replace('{"or_no", "or_date", "check_no", "check_date"}','{"or_no", "or_date", "check_no", "check_date", "customer_name"}')
s=s.replace('<td colspan="4">Group total','<td colspan="5">Group total')
assert '("Customer", "customer_name")' in s
assert 'colspan="5">Group total' in s
p.write_text(s)
print('LOCAL_PRINT_CUSTOMER_UPDATED')
