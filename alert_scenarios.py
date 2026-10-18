from __future__ import annotations
import importlib.util, json, random, statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE=Path(__file__).resolve().parent
OUT=HERE/'run_tests'/'alerts'
OUT.mkdir(parents=True,exist_ok=True)
spec=importlib.util.spec_from_file_location('reviewpulse_agent',HERE/'reviewpulse_agent.py')
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
Agent=m.ReviewPulseAgent
PHRASES=m.PHRASES
SCENARIOS=[
 {'id':'A1','name':'sin cambio bajo','base':[0.10,0.10,0.10],'target':0.10,'n':20,'expected':False},
 {'id':'A2','name':'sin cambio alto','base':[0.30,0.30,0.30],'target':0.30,'n':20,'expected':False},
 {'id':'A3','name':'aumento menor al umbral','base':[0.10,0.10,0.10],'target':0.25,'n':20,'expected':False},
 {'id':'A4','name':'aumento positivo','base':[0.10,0.10,0.10],'target':0.35,'n':20,'expected':True},
 {'id':'A5','name':'aumento marcado','base':[0.20,0.20,0.20],'target':0.50,'n':20,'expected':True},
 {'id':'A6','name':'justo en el umbral estricto','base':[0.20,0.20,0.20],'target':0.40,'n':20,'expected':False},
 {'id':'A7','name':'línea base variable','base':[0.10,0.30,0.10],'target':0.40,'n':20,'expected':True},
 {'id':'A8','name':'volumen insuficiente','base':[0.20,0.20,0.20],'target':1.00,'n':2,'expected':False},
 {'id':'A9','name':'aumento desde base alta','base':[0.50,0.50,0.50],'target':0.75,'n':20,'expected':True},
 {'id':'A10','name':'sin historial','base':[],'target':0.90,'n':20,'expected':False},
]
all_runs=[]; by_scenario=[]
start=datetime(2026,1,5,tzinfo=timezone.utc)
for si,sc in enumerate(SCENARIOS):
  scenario_runs=[]
  for rep in range(5):
    seed=5000+si*100+rep
    rng=random.Random(seed)
    root=OUT/sc['id']/f'rep_{rep+1}'
    agent=Agent(root,include_seed=True,load_feedback=False)
    if agent.log_path.exists(): agent.log_path.unlink()
    results=[]; weeks=sc['base']+[sc['target']]
    for wi,rate in enumerate(weeks):
      volume=sc['n'] if wi==len(weeks)-1 else 20
      negatives=round(rate*volume)
      sentiments=['negativo']*negatives+['positivo']*(volume-negatives)
      rng.shuffle(sentiments)
      for j,sent in enumerate(sentiments):
        topic=rng.choice(tuple(PHRASES))
        text=rng.choice(PHRASES[topic][sent])
        dt=start+timedelta(days=wi*7,minutes=j*3)
        results.append(agent.process({'review_id':f'{sc["id"]}-{rep+1}-{wi+1}-{j+1}','text':text,'published_at':dt.isoformat(),'source':'simulador_alertas','rating':rng.randint(1,5)}))
    reports=agent.weekly_reports(results)
    target_week=reports[-1] if reports else None
    target_alert=bool(target_week and target_week['alert'])
    actual_alerts=[r for r in reports if r['alert']]
    tp=int(sc['expected'] and target_alert)
    fp=len(actual_alerts)-tp
    fn=int(sc['expected'] and not target_alert)
    complete=sum(all(k in r for k in ('week','review_count','negative_rate','topic_counts','alert','alert_reason')) and (not r['alert'] or bool(r['alert_reason'])) for r in reports)
    rep_precision=tp/max(1,len(actual_alerts))
    rep_recall=(tp if sc['expected'] else None)
    run={'scenario':sc['id'],'name':sc['name'],'rep':rep+1,'seed':seed,'expected_alert':sc['expected'],'target_alert':target_alert,'correct_target_outcome':target_alert==sc['expected'],'alerts_total':len(actual_alerts),'tp':tp,'fp':fp,'fn':fn,'reports':len(reports),'complete_reports':complete,'report_completeness':complete/max(1,len(reports)),'precision':rep_precision,'reports_detail':reports}
    scenario_runs.append(run); all_runs.append(run)
  vals=[int(r['correct_target_outcome']) for r in scenario_runs]
  pre=[r['precision'] for r in scenario_runs]
  rec=[int(r['tp']) for r in scenario_runs] if sc['expected'] else []
  by_scenario.append({'scenario':sc['id'],'name':sc['name'],'expected_alert':sc['expected'],'runs':5,'correct':sum(vals),'outcome_accuracy_mean':statistics.mean(vals),'outcome_accuracy_sd':statistics.stdev(vals),'precision_mean':statistics.mean(pre),'precision_sd':statistics.stdev(pre),'recall_mean':statistics.mean(rec) if rec else None,'recall_sd':statistics.stdev(rec) if len(rec)>1 else None,'report_completeness':statistics.mean(r['report_completeness'] for r in scenario_runs),'report_completeness_sd':statistics.stdev(r['report_completeness'] for r in scenario_runs)})
TP=sum(r['tp'] for r in all_runs); FP=sum(r['fp'] for r in all_runs); FN=sum(r['fn'] for r in all_runs)
positive=sum(1 for r in all_runs if r['expected_alert']); total_alerts=sum(r['alerts_total'] for r in all_runs)
prec=TP/max(1,total_alerts); recall=TP/max(1,positive)
per_run_precision=[r['precision'] for r in all_runs if r['expected_alert']]
per_run_recall=[int(r['tp']) for r in all_runs if r['expected_alert']]
report_ratios=[r['report_completeness'] for r in all_runs]
summary={'scenario_count':len(SCENARIOS),'repetitions_each':5,'runs':len(all_runs),'expected_outcome_accuracy':sum(r['correct_target_outcome'] for r in all_runs)/len(all_runs),'expected_outcome_accuracy_sd':statistics.stdev(int(r['correct_target_outcome']) for r in all_runs),'true_alerts':TP,'false_alerts':FP,'missed_increases':FN,'total_alerts':total_alerts,'precision_micro':prec,'precision_mean_per_positive_run':statistics.mean(per_run_precision),'precision_sd_per_positive_run':statistics.stdev(per_run_precision),'recall':recall,'recall_sd_per_positive_trial':statistics.stdev(per_run_recall),'report_completeness':sum(r['complete_reports'] for r in all_runs)/sum(r['reports'] for r in all_runs),'report_completeness_mean':statistics.mean(report_ratios),'report_completeness_sd':statistics.stdev(report_ratios),'mean_reports_per_run':statistics.mean(r['reports'] for r in all_runs),'sd_reports_per_run':statistics.stdev(r['reports'] for r in all_runs),'complete_four_week_windows':sum(r['reports']==4 for r in all_runs if r['scenario']!='A10'),'four_week_window_scenarios':9,'four_week_window_repetitions_per_scenario':5}
output={'summary':summary,'by_scenario':by_scenario,'runs':all_runs}
(HERE/'alert_test_results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'summary':summary,'by_scenario':by_scenario},ensure_ascii=False,indent=2))

