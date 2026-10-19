# REVIEWPULSE-AGENT

Prototipo local de un agente de aprendizaje para analizar reseñas hoteleras en español. Puede entrenarse y evaluarse con los archivos español de Trip-MAML, ejecutar una demostración estocástica, clasificar polaridad y tema principal, generar agregados semanales y aprender de correcciones humanas.

## Requisitos

- Python 3.10 o superior.
- Dependencia web: Streamlit (instalada con `requirements.txt`).
- No usa LLM ni APIs externas.

## Interfaz web

Instalen las dependencias e inicien la aplicación:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

La interfaz permite analizar una reseña, ejecutar el simulador estocástico y correr la batería de 50 pruebas funcionales (10 escenarios, cinco repeticiones). Desde la web se descargan los resultados y los logs JSONL. El despliegue usa almacenamiento temporal: descarguen la evidencia antes de que la instancia se reinicie.

Para desplegar en Streamlit Community Cloud, publiquen `app.py`, `reviewpulse_agent.py` y `requirements.txt` en el repositorio y seleccionen `app.py` como archivo principal. La demo web usa el conocimiento inicial del prototipo; el entrenamiento/evaluación de Trip-MAML sigue el proceso local descrito abajo porque el corpus no se distribuye con la aplicación.

## Obtener y preparar Trip-MAML

Descarguen `spanish_training.json` y `spanish_test.json` desde la carpeta `ES` del [repositorio oficial de Trip-MAML](https://github.com/diegma/trip-maml/tree/main/ES). Guárdenlos localmente, por ejemplo en `data/raw/`. El programa lee archivos JSON Lines (un objeto JSON por renglón); no es necesario convertirlos manualmente.

No publiquen los archivos de datos ni logs que contengan reseñas hasta confirmar las condiciones de uso y redistribución del corpus. El `.gitignore` excluye las carpetas de datos y las ejecuciones locales.

## Entrenar y evaluar con Trip-MAML

```bash
python reviewpulse_agent.py --tripmaml-train data/raw/spanish_training.json --tripmaml-test data/raw/spanish_test.json --count 0 --out run_tripmaml
```

El programa convierte las anotaciones a ejemplos por reseña, entrena solo con `spanish_training.json` y evalúa exclusivamente con `spanish_test.json`. Comprueba que ningún `reviewId` esté en ambos archivos y se detiene si detecta solapamiento. La conversión reconstruye el texto superficial a partir de `segments`, eliminando POS, lema y marcas auxiliares.

Para corresponder con la salida de una sola polaridad y un tema principal del diseño, se deriva la polaridad por mayoría de las etiquetas por oración y el tema principal por frecuencia de aspectos. Los empates se resuelven en un orden de clases fijo. Los aspectos se agrupan así: Rooms y SleepQuality → habitación; Cleanliness → limpieza; Service y Checkin → servicio; Value → precio; Location → ubicación; Other, Food, Building y Business → otros. NotRelated se excluye. Las polaridades p/n/x se mapean a positivo/negativo/neutral.

Archivos de resultado:

- `run_tripmaml/tripmaml_evaluation.json`: exactitud y macro-F1 de tema y polaridad, exactitud conjunta y conteos.
- `run_tripmaml/execution.jsonl`: percepciones, predicciones y acciones con marcas de tiempo UTC.
- `run_tripmaml/summary.json`: resumen de ejecución.

### Resultado de la ejecución recibida

Con los archivos compartidos, el sistema entrenó con **291 reseñas utilizables** (una fila sin etiquetas útiles se omitió) y evaluó **125 reseñas**. No hubo `reviewId` compartidos entre los conjuntos.

| Medida | Resultado | Meta/detalle |
|---|---:|---|
| Exactitud de polaridad | 92,8 % | Supera 85 % para esta etiqueta derivada |
| Macro-F1 de polaridad | 57,2 % | Reporta el efecto del desbalance de clases |
| Exactitud del tema principal | 52,0 % | No alcanza 85 % |
| Macro-F1 del tema principal | 18,0 % | El modelo tiene dificultad en clases minoritarias |
| Exactitud conjunta (tema y polaridad correctos) | 48,0 % | **No alcanza la meta global de 85 %** |

Estas cifras corresponden a una evaluación exploratoria del baseline Naive Bayes y a etiquetas derivadas por mayoría. No equivalen a una evaluación con etiquetas originales por oración/aspecto ni validan BETO. Deben reportarse con esta limitación.

## Demostración del entorno estocástico

```bash
python reviewpulse_agent.py --count 60 --seed 42 --out run_demo
```

La semilla reproduce el texto, la calificación y las fechas simuladas. El simulador introduce azar y aumenta la probabilidad de reseñas negativas en la última semana. La simulación permite demostrar agregados semanales y alertas; Trip-MAML no incluye el historial temporal requerido para probar esa función con datos reales.

## Correcciones humanas

Se puede suministrar un CSV UTF-8 con columnas `text,topic,sentiment`:

```bash
python reviewpulse_agent.py --count 60 --seed 42 --out run_demo --feedback correcciones.csv
```

Las correcciones se guardan en `learned_feedback.csv` y se cargan en ejecuciones futuras de esa carpeta. Los valores válidos para topic: `limpieza`, `servicio`, `ubicacion`, `precio`, `habitacion`, `otros`; para sentiment: `positivo`, `neutral`, `negativo`.

## Ciclo del agente

1. **Percepción:** `perceive()` valida y normaliza texto, fecha, identificador, fuente y puntuación.
2. **Decisión:** `decide()` usa dos clasificadores Naive Bayes multinomiales para polaridad y tema principal; calcula confianza y deriva casos de baja confianza a revisión.
3. **Acción:** `act()` registra percepción, decisión y acción en JSONL. `weekly_reports()` calcula resúmenes y alerta si una tasa negativa semanal supera en 20 puntos porcentuales la línea base y se supera el mínimo de reseñas.
4. **Aprendizaje:** las anotaciones del conjunto de entrenamiento ajustan el clasificador; `apply_feedback()` añade correcciones humanas posteriores.

## Pruebas de Fase 3

El protocolo, los umbrales, los 10 escenarios, cinco repeticiones por escenario y el análisis de resultados están en `fase3_protocolo.md` y `fase3_pruebas.md`. Para reproducir la batería funcional y las cinco corridas del simulador:

```bash
python scenario_tests.py
```

Los resultados se escriben en `scenario_test_results.json`; los logs de evidencia quedan en `run_tests/`. El programa también registra con timestamp las entradas inválidas rechazadas, junto con su motivo y acción de rechazo. La exactitud del modelo debe leerse por separado en `run_tripmaml/tripmaml_evaluation.json`: el test fijo obtuvo 48,0 % de exactitud conjunta, por debajo de la meta de 85 %.

Para reproducir los diez escenarios de alerta y completitud del reporte (cinco repeticiones por escenario):

```bash
python alert_scenarios.py
```

Los resultados agregados quedan en `alert_test_results.json`; los logs individuales se guardan bajo `run_tests/alerts/`. La batería cubre alertas, reportes completos y nueve escenarios de ventanas de cuatro semanas.

## Cambios respecto del diseño inicial

BETO fue reemplazado en este prototipo por Naive Bayes multinomial, sin dependencias externas. El objetivo de una sola polaridad y tema principal se obtiene agregando las anotaciones de Trip-MAML por mayoría. Esta simplificación pierde información cuando una reseña contiene varios aspectos con polaridades distintas. El prototipo no se conecta a plataformas ni envía alertas al hotel. La sección de implementación describe los cambios y sus motivos.

Si desean medir la tarea original de Trip-MAML en forma más fiel, la siguiente mejora es una salida multiaspecto por oración, en lugar de una sola etiqueta de tema por reseña.

