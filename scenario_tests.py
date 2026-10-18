from __future__ import annotations
import importlib.util, json, random, statistics
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / 'run_tests'
RUNS.mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location('reviewpulse_agent', HERE / 'reviewpulse_agent.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ReviewPulseAgent = module.ReviewPulseAgent
StochasticReviewEnvironment = module.StochasticReviewEnvironment

SCENARIOS = [
    ('S1 positiva común', lambda rng: {'text': 'La habitación está limpia y el personal es amable.' + rng.choice(['', ' Muy bien.']), 'rating': 5}),
    ('S2 negativa común', lambda rng: {'text': 'El servicio fue lento y la habitación estaba sucia.' + rng.choice(['', ' No volvería.']), 'rating': 1}),
    ('S3 reseña muy corta', lambda rng: {'text': rng.choice(['Regular.', 'Bien.', 'Mal.']), 'rating': 3}),
    ('S4 varios aspectos', lambda rng: {'text': 'La ubicación es excelente, pero la habitación estaba sucia y el desayuno frío.'}),
    ('S5 tildes, puntuación y emoji', lambda rng: {'text': '¡Qué atención tan pésima! 😕 La ubicación, eso sí, es magnífica.'}),
    ('S6 texto largo', lambda rng: {'text': ('El personal fue amable, la ubicación muy buena, pero el baño estaba sucio. ' * rng.randint(15, 30))}),
    ('S7 faltan metadatos opcionales', lambda rng: {'text': 'El precio fue razonable y el servicio correcto.'}),
    ('S8 campos extra desconocidos', lambda rng: {'text': 'La habitación fue cómoda.', 'source': 'prueba', 'extra': {'campo': 1}, 'rating': None}),
    ('S9 texto vacío (falla esperada)', lambda rng: {'text': '', 'rating': 4}),
    ('S10 texto solo espacios (falla esperada)', lambda rng: {'text': '   \t  ', 'rating': None}),
]
scenario_results=[]
for i,(name,make_input) in enumerate(SCENARIOS):
    outcomes=[]
    for rep in range(5):
        rng=random.Random(2000+i*10+rep)
        raw=make_input(rng)
        raw.update({'review_id':f'test-{i+1}-{rep+1}', 'published_at':'2026-01-05T12:00:00+00:00', 'source':raw.get('source','prueba_funcional')})
        expected_error=i>=8
        outdir=RUNS/'scenarios'/f's{i+1:02d}_r{rep+1:02d}'
        agent=ReviewPulseAgent(outdir, include_seed=True, load_feedback=False)
        if agent.log_path.exists():
            agent.log_path.unlink()
        try:
            result=agent.process(raw)
            loglines=agent.log_path.read_text(encoding='utf-8').splitlines()
            rec=json.loads(loglines[-1])
            has_cycle=all(k in rec for k in ('timestamp','perception','decision','action'))
            ok=(not expected_error and bool(result['decision']) and bool(result['action']['stored_prediction']) and has_cycle)
            outcome={'passed':bool(ok),'rejected_as_expected':False,'log_has_cycle':bool(has_cycle)}
        except ValueError as e:
            loglines=agent.log_path.read_text(encoding='utf-8').splitlines() if agent.log_path.exists() else []
            rec=json.loads(loglines[-1]) if loglines else {}
            has_cycle=all(k in rec for k in ('timestamp','perception','decision','action'))
            rejected=bool(rec.get('action',{}).get('rejected'))
            ok=expected_error and has_cycle and rejected
            outcome={'passed':bool(ok),'rejected_as_expected':bool(expected_error),'error':str(e),'log_has_cycle':bool(has_cycle),'log_has_rejection':rejected}
        outcomes.append(outcome)
    vals=[int(x['passed']) for x in outcomes]
    scenario_results.append({'scenario':name,'runs':5,'passed':sum(vals),'rate':sum(vals)/5,'mean':statistics.mean(vals),'stdev':statistics.stdev(vals),'details':outcomes})

sim_runs=[]
for rep in range(5):
    seed=101+rep
    outdir=RUNS/'simulator'/f'seed_{seed}'
    start=datetime(2026,1,5,tzinfo=timezone.utc)
    env=StochasticReviewEnvironment(seed=seed, start=start)
    agent=ReviewPulseAgent(outdir, include_seed=True, load_feedback=False)
    if agent.log_path.exists():
        agent.log_path.unlink()
    raw=env.generate(28)
    results=[agent.process({k:v for k,v in row.items() if k!='simulation_truth'}) for row in raw]
    reports=agent.weekly_reports(results)
    truth_by_week={}
    for row in raw:
        week=row['published_at'][:10]
        from datetime import date
        iso=date.fromisoformat(week).isocalendar()
        week_key=f'{iso.year}-W{iso.week:02d}'
        bucket=truth_by_week.setdefault(week_key,{'n':0,'negative':0})
        bucket['n']+=1
        bucket['negative']+=row['simulation_truth']['sentiment']=='negativo'
    alerted={r['week']:bool(r['alert']) for r in reports}
    sim_accuracy=sum(x['decision']['topic']==y['simulation_truth']['topic'] and x['decision']['sentiment']==y['simulation_truth']['sentiment'] for x,y in zip(results,raw))/len(raw)
    target_week='2026-W05'  # cuarta semana operativa con aumento de negatividad
    sim_runs.append({'seed':seed,'processed':len(results),'reports':len(reports),'alerts':sum(r['alert'] for r in reports),'weeks':[r['week'] for r in reports],
                     'simulation_joint_accuracy':sim_accuracy,'target_week':target_week,'target_week_alert':alerted.get(target_week,False),
                     'target_week_truth_negative_rate':truth_by_week.get(target_week,{}).get('negative',0)/max(1,truth_by_week.get(target_week,{}).get('n',0)),
                     'non_target_alerts':sum(v for wk,v in alerted.items() if wk!=target_week)})

results={'scenario_tests':scenario_results,
         'scenario_summary':{'total_scenarios':len(scenario_results),'repetitions_each':5,'total_attempts':50,'passed':sum(x['passed'] for x in scenario_results),'expected_behavior_pass_rate':sum(x['passed'] for x in scenario_results)/50},
         'simulator_repetitions':sim_runs,
         'simulator_summary':{'runs':5,'mean_processed':statistics.mean(x['processed'] for x in sim_runs),'sd_processed':statistics.stdev(x['processed'] for x in sim_runs),'mean_reports':statistics.mean(x['reports'] for x in sim_runs),'sd_reports':statistics.stdev(x['reports'] for x in sim_runs),'mean_alerts':statistics.mean(x['alerts'] for x in sim_runs),'sd_alerts':statistics.stdev(x['alerts'] for x in sim_runs),
                              'mean_joint_accuracy':statistics.mean(x['simulation_joint_accuracy'] for x in sim_runs),'sd_joint_accuracy':statistics.stdev(x['simulation_joint_accuracy'] for x in sim_runs),
                              'target_week_detection_rate':sum(x['target_week_alert'] for x in sim_runs)/5,'target_week_precision':sum(x['target_week_alert'] for x in sim_runs)/max(1,sum(x['alerts'] for x in sim_runs)),
                              'mean_non_target_alerts':statistics.mean(x['non_target_alerts'] for x in sim_runs),'sd_non_target_alerts':statistics.stdev(x['non_target_alerts'] for x in sim_runs)}}
(HERE/'scenario_test_results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'scenario_summary':results['scenario_summary'],'simulator_summary':results['simulator_summary'],'simulator_repetitions':sim_runs,'scenario_passes':[(x['scenario'],x['passed'],x['stdev']) for x in scenario_results]},ensure_ascii=False,indent=2))


