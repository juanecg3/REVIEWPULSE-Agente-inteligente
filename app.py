"""Interfaz web de REVIEWPULSE-AGENT hecha con Streamlit."""
from __future__ import annotations

import json
import random
import statistics
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from reviewpulse_agent import (
    ReviewPulseAgent,
    StochasticReviewEnvironment,
    TOPICS,
    SENTIMENTS,
)


st.set_page_config(
    page_title="ReviewPulse | Analizador de reseñas",
    page_icon="💬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container {max-width: 1180px; padding-top: 2rem; padding-bottom: 3rem;}
    /* La barra lateral mantiene contraste alto tanto en tema claro como oscuro. */
    [data-testid="stSidebar"] {background: #142b4a !important;}
    [data-testid="stSidebar"] * {color: #f7f9fc !important;}
    [data-testid="stSidebar"] [data-baseweb="radio"] > div {background: transparent !important;}
    [data-testid="stSidebar"] [data-testid="stRadio"] label {color: #f7f9fc !important;}
    [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {color: #ffffff !important;}
    [data-testid="stSidebar"] [data-testid="stRadio"] input:checked + div {border-color: #79c8ff !important;}
    [data-testid="stSidebar"] [data-testid="stRadio"] input:checked + div > div {background: #79c8ff !important;}
    [data-testid="stSidebar"] button, [data-testid="stSidebar"] [role="button"] {color: #f7f9fc !important;}
    [data-testid="stSidebar"] svg {color: #f7f9fc !important; fill: currentColor;}
    .hero {padding: 1.5rem 1.8rem; border-radius: 18px; background: linear-gradient(120deg,#142b4a,#275b84); color:white; margin-bottom:1.2rem;}
    .hero h1 {margin:0 0 .3rem 0; color:white; font-size:2.1rem;}
    .hero p {margin:0; opacity:.88;}
    .small-note {color:#627187; font-size:.92rem;}
</style>
<div class="hero"><h1>💬 ReviewPulse</h1><p>Agente inteligente para clasificar reseñas hoteleras y detectar cambios en la experiencia de los huéspedes.</p></div>
""", unsafe_allow_html=True)


def new_run_dir(label: str) -> Path:
    """Crea un área temporal por ejecución; nada se conserva entre sesiones del servidor."""
    base = Path(tempfile.gettempdir()) / "reviewpulse-web"
    base.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=f"{label}-", dir=base))
    return folder


def log_archive(log_paths: list[Path], results: dict) -> bytes:
    """Empaqueta el log JSONL y el resumen descargable de la ejecución."""
    from io import BytesIO

    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("resultados.json", json.dumps(results, ensure_ascii=False, indent=2))
        for index, path in enumerate(log_paths, start=1):
            if path.exists():
                archive.write(path, f"logs/ejecucion_{index}.jsonl")
    return stream.getvalue()


def run_functional_battery() -> tuple[dict, bytes]:
    """Ejecuta 10 escenarios funcionales con 5 repeticiones, incluidos 2 errores esperados."""
    scenarios = [
        ("Reseña positiva común", lambda rng: {"text": "La habitación está limpia y el personal es amable.", "rating": 5}, False),
        ("Reseña negativa común", lambda rng: {"text": "El servicio fue lento y la habitación estaba sucia.", "rating": 1}, False),
        ("Reseña muy corta", lambda rng: {"text": rng.choice(["Regular.", "Bien.", "Mal."]), "rating": 3}, False),
        ("Varios aspectos", lambda rng: {"text": "La ubicación es excelente, pero la habitación estaba sucia y el desayuno frío."}, False),
        ("Tildes, puntuación y emoji", lambda rng: {"text": "¡Qué atención tan pésima! 😕 La ubicación, eso sí, es magnífica."}, False),
        ("Texto largo", lambda rng: {"text": "El personal fue amable, la ubicación muy buena, pero el baño estaba sucio. " * rng.randint(15, 30)}, False),
        ("Metadatos opcionales ausentes", lambda rng: {"text": "El precio fue razonable y el servicio correcto."}, False),
        ("Campo adicional desconocido", lambda rng: {"text": "La habitación fue cómoda.", "extra": {"campo": 1}}, False),
        ("Texto vacío (falla esperada)", lambda rng: {"text": "", "rating": 4}, True),
        ("Solo espacios (falla esperada)", lambda rng: {"text": "   \t  ", "rating": None}, True),
    ]
    root = new_run_dir("pruebas")
    results, logs = [], []
    for i, (name, make_input, expects_error) in enumerate(scenarios):
        passed = []
        for repetition in range(5):
            out = root / f"caso_{i+1:02d}_rep_{repetition+1:02d}"
            agent = ReviewPulseAgent(out, include_seed=True, load_feedback=False)
            raw = make_input(random.Random(2000 + i * 10 + repetition))
            raw.update({"review_id": f"web-{i+1}-{repetition+1}", "published_at": "2026-01-05T12:00:00+00:00", "source": "interfaz_web"})
            try:
                result = agent.process(raw)
                ok = not expects_error and bool(result["decision"]) and result["action"].get("stored_prediction")
            except ValueError:
                ok = expects_error
            passed.append(int(bool(ok)))
            if agent.log_path.exists():
                logs.append(agent.log_path)
        results.append({"Escenario": name, "Repeticiones": 5, "Aprobadas": sum(passed), "Tasa": sum(passed) / 5, "Media": statistics.mean(passed), "Desv. estándar": statistics.stdev(passed)})
    summary = {"casos": results, "total_pruebas": 50, "aprobadas": sum(row["Aprobadas"] for row in results), "tasa_global": sum(row["Aprobadas"] for row in results) / 50}
    return summary, log_archive(logs, summary)


def run_simulation(count: int, seed: int) -> tuple[list[dict], list[dict], bytes]:
    root = new_run_dir("simulacion")
    agent = ReviewPulseAgent(root, include_seed=True, load_feedback=False)
    environment = StochasticReviewEnvironment(seed=seed)
    raw_reviews = environment.generate(count)
    results = [agent.process({key: value for key, value in raw.items() if key != "simulation_truth"}) for raw in raw_reviews]
    reports = agent.weekly_reports(results)
    summary = {
        "tipo": "simulación estocástica",
        "semilla": seed,
        "reseñas_procesadas": len(results),
        "casos_derivados_a_revisión": sum(row["decision"]["needs_human_review"] for row in results),
        "reportes_semanales": reports,
    }
    return results, reports, log_archive([agent.log_path], summary)


with st.sidebar:
    st.title("Navegación")
    page = st.radio("Selecciona una sección", ["Analizar reseña", "Simulación", "Pruebas", "Acerca del agente"], label_visibility="collapsed")
    st.divider()
    st.caption("Prototipo académico · Naive Bayes multinomial · Sin API externa ni LLM")


if page == "Analizar reseña":
    st.subheader("Analiza una reseña")
    st.write("Escribe una reseña y el agente estimará su polaridad y el tema principal.")
    with st.form("review_form"):
        review_text = st.text_area("Texto de la reseña", placeholder="Ej.: La habitación estaba limpia y el personal fue muy amable.", height=140)
        left, right = st.columns(2)
        with left:
            rating_choice = st.selectbox("Calificación (opcional)", ["Sin calificación", 1, 2, 3, 4, 5], format_func=lambda x: x if isinstance(x, str) else f"{x} / 5")
            rating = None if rating_choice == "Sin calificación" else rating_choice
        with right:
            source = st.text_input("Fuente", value="entrada_manual")
        submitted = st.form_submit_button("Analizar reseña", type="primary", use_container_width=True)
    if submitted:
        run_dir = new_run_dir("analisis")
        agent = ReviewPulseAgent(run_dir, include_seed=True, load_feedback=False)
        try:
            result = agent.process({"text": review_text, "rating": rating, "source": source, "review_id": f"manual-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"})
            decision = result["decision"]
            st.session_state["last_analysis"] = (result, agent.log_path)
            a, b, c = st.columns(3)
            a.metric("Polaridad", decision["sentiment"].capitalize())
            b.metric("Tema principal", decision["topic"].capitalize())
            c.metric("Confianza", f"{decision['confidence']:.0%}")
            if decision["needs_human_review"]:
                st.warning("La confianza está por debajo del umbral; el agente deriva esta reseña a revisión humana.")
            else:
                st.success("El agente registró la predicción y la añadió al agregado semanal.")
            with st.expander("Ver percepción, decisión y acción"):
                st.json(result)
        except ValueError as error:
            st.error(str(error))
            if agent.log_path.exists():
                st.info("El intento rechazado también quedó registrado en el log.")
                st.download_button("Descargar log de rechazo", agent.log_path.read_bytes(), "reviewpulse_rechazo.jsonl", "application/jsonl")
    if "last_analysis" in st.session_state:
        result, log_path = st.session_state["last_analysis"]
        st.download_button("Descargar evidencia de esta ejecución", log_path.read_bytes(), "reviewpulse_analisis.jsonl", "application/jsonl")

elif page == "Simulación":
    st.subheader("Simulación de reseñas y alertas")
    st.write("Genera reseñas sintéticas con ruido aleatorio y una mayor proporción de opiniones negativas al final del periodo.")
    with st.form("simulation_form"):
        col1, col2 = st.columns(2)
        count = col1.slider("Cantidad de reseñas", min_value=10, max_value=120, value=60, step=10)
        seed = col2.number_input("Semilla reproducible", min_value=0, max_value=999999, value=42, step=1)
        go = st.form_submit_button("Ejecutar agente desde cero", type="primary", use_container_width=True)
    if go:
        with st.spinner("El agente está percibiendo, clasificando y registrando las reseñas..."):
            results, reports, archive = run_simulation(count, int(seed))
        st.session_state["simulation"] = (results, reports, archive)
    if "simulation" in st.session_state:
        results, reports, archive = st.session_state["simulation"]
        m1, m2, m3 = st.columns(3)
        m1.metric("Reseñas procesadas", len(results))
        m2.metric("Reportes semanales", len(reports))
        m3.metric("Derivadas a revisión", sum(row["decision"]["needs_human_review"] for row in results))
        if reports:
            st.markdown("#### Evolución semanal")
            st.line_chart({"Tasa de reseñas negativas": {row["week"]: row["negative_rate"] for row in reports}})
            table = [{"Semana": row["week"], "Reseñas": row["review_count"], "Negativas": row["negative_count"], "Tasa negativa": f"{row['negative_rate']:.0%}", "Alerta": "Sí" if row["alert"] else "No"} for row in reports]
            st.dataframe(table, use_container_width=True, hide_index=True)
            alerts = [row for row in reports if row["alert"]]
            for alert in alerts:
                st.warning(f"Alerta en {alert['week']}: {alert['alert_reason']}")
        with st.expander("Ver primeras decisiones del agente"):
            st.dataframe([{"Reseña": row["perception"]["text"], "Polaridad": row["decision"]["sentiment"], "Tema": row["decision"]["topic"], "Confianza": row["decision"]["confidence"], "Revisión humana": row["decision"]["needs_human_review"]} for row in results[:15]], use_container_width=True, hide_index=True)
        st.download_button("Descargar resultados y logs completos", archive, "reviewpulse_simulacion.zip", "application/zip")
        st.caption("Las reseñas son sintéticas y las alertas solo ilustran el prototipo; no representan un hotel real.")

elif page == "Pruebas":
    st.subheader("Pruebas reproducibles")
    st.write("Batería funcional de 10 escenarios con cinco repeticiones cada uno: 50 intentos, incluidos dos tipos de entrada inválida esperada.")
    st.info("Criterio de aceptación: las reseñas válidas deben procesarse y registrarse; las entradas inválidas deben rechazarse y dejar constancia en el log. La tasa es una proporción de intentos que cumplieron esa regla.")
    with st.expander("¿Por qué pueden salir iguales la tasa, la media y la desviación estándar?"):
        st.markdown("""
        Cada repetición produce un resultado binario: **1** si ocurrió el comportamiento esperado y **0** si no. En esta batería, las variaciones aleatorias de algunos textos no cambian la regla evaluada: por ejemplo, una reseña válida cuenta como aprobada siempre que se procese y se registre.

        Por eso, si un escenario aprueba sus cinco intentos, su tasa y media son **1,00 (100 %)** y su desviación estándar es **0,00**. Si los cinco fallan, son **0,00** y **0,00**. La repetición ayuda a mostrar que el comportamiento se sostuvo, pero esta medida no evalúa si la clasificación de tema y polaridad fue correcta.

        La variación entre semillas se observa en **Simulación**, donde cambian las reseñas generadas, las predicciones y los reportes semanales. La exactitud predictiva se mide aparte con las etiquetas de prueba de Trip-MAML.
        """)
    if st.button("Ejecutar 50 pruebas ahora", type="primary"):
        with st.spinner("Ejecutando escenarios y guardando logs con marca de tiempo..."):
            summary, archive = run_functional_battery()
        st.session_state["test_results"] = (summary, archive)
    if "test_results" in st.session_state:
        summary, archive = st.session_state["test_results"]
        a, b = st.columns(2)
        a.metric("Pruebas aprobadas", f"{summary['aprobadas']} / {summary['total_pruebas']}")
        b.metric("Tasa global", f"{summary['tasa_global']:.0%}")
        st.dataframe([{**row, "Tasa": f"{row['Tasa']:.0%}", "Media": f"{row['Media']:.2f}", "Desv. estándar": f"{row['Desv. estándar']:.2f}"} for row in summary["casos"]], use_container_width=True, hide_index=True)
        st.download_button("Descargar tabla y logs de evidencia", archive, "reviewpulse_pruebas.zip", "application/zip")
        st.caption("Estas pruebas verifican el ciclo y el manejo de errores. La calidad predictiva debe reportarse aparte con el conjunto de prueba Trip-MAML.")

else:
    st.subheader("Guía completa de ReviewPulse")
    st.markdown("""
    ### ¿Qué es ReviewPulse?

    ReviewPulse es un prototipo académico de **agente de aprendizaje supervisado** que recibe reseñas hoteleras y produce dos estimaciones: la **polaridad** (positiva, neutral o negativa) y el **tema principal** (limpieza, servicio, ubicación, precio, habitación u otros). Su propósito es mostrar el ciclo de un agente —percibir, decidir y actuar—, no sustituir un sistema de gestión hotelera real.

    La aplicación ofrece tres formas de observarlo: analizar una reseña escrita por la persona que la usa, generar reseñas sintéticas para explorar reportes y alertas, y ejecutar una batería de pruebas funcionales. Ninguna de esas pantallas muestra una tabla de resultados preparada con anterioridad: cada botón ejecuta el código del agente en el momento.

    ### ¿Qué hace cada sección?

    **Analizar reseña.** Escribe una reseña en español y, si quieres, especifica una calificación de 1 a 5 y una fuente. Al pulsar *Analizar reseña*, ReviewPulse intenta clasificarla. La pantalla muestra la polaridad, el tema y la confianza; el panel expandible permite inspeccionar la percepción recibida, la decisión y la acción realizada. El botón de descarga entrega el registro JSONL de esa ejecución.

    Si la confianza conjunta es menor que el umbral interno de **0,42**, el agente marca `needs_human_review` y la página lo señala. La confianza se calcula como la menor confianza entre las predicciones de tema y polaridad: si una de las dos es débil, el caso se deriva a revisión. No es una probabilidad calibrada de que toda la respuesta sea correcta.

    Para demostrar una falla esperada, envía el formulario vacío. El agente debe rechazarlo porque no hay texto que clasificar y la interfaz ofrece descargar el log del rechazo. Un rechazo correcto cuenta como comportamiento esperado; no significa que la aplicación se haya averiado.

    **Simulación.** Elige la cantidad de reseñas sintéticas y una semilla, y pulsa *Ejecutar agente desde cero*. Se genera una instancia nueva del agente, un conjunto nuevo de percepciones y reportes semanales. La semilla permite repetir la misma secuencia; al cambiarla, cambian las reseñas aleatorias y pueden cambiar las predicciones, los niveles de confianza y las alertas.

    Los reportes indican cuántas reseñas hubo cada semana, cuántas se clasificaron como negativas y qué proporción representan. Se activa una alerta cuando una semana tiene el mínimo de reseñas requerido y su tasa negativa supera en más de **20 puntos porcentuales** el promedio de las semanas anteriores. La primera semana no puede activar esa comparación porque aún no existe una línea base. El gráfico y la tabla reflejan las salidas que el agente calculó en esa ejecución; no son estadísticas históricas de un hotel.

    El ZIP descargable incluye el resumen y el log de ejecución. Cada registro conserva una marca de tiempo, la percepción, la predicción y la acción. Las reseñas son sintéticas; esta función sirve para demostrar el simulador, los agregados y las alertas, no para afirmar que un establecimiento real tuvo un problema.

    **Pruebas.** El botón ejecuta diez escenarios cinco veces cada uno (50 intentos): ocho entradas que deben procesarse y dos entradas inválidas —texto vacío y solo espacios— que deben rechazarse. Se verifica la conducta funcional y que el agente registre la ejecución. La página muestra aprobados, tasa, media y desviación estándar de cada escenario y permite descargar los resultados junto con los logs.

    Cada intento se resume como **1** si cumple lo esperado o **0** si no. Por tanto, cinco aprobaciones dan tasa y media de 100 % y desviación estándar de 0; cinco fallas dan 0 % y desviación 0. Esos números evalúan si el agente procesó, rechazó y registró como debía. No comparan sus etiquetas con una respuesta correcta, por lo que **no miden la precisión de la clasificación**. Que se aprueben las pruebas funcionales no implica que el tema y la polaridad siempre sean correctos.

    ### ¿De dónde salen las predicciones?

    El razonamiento está implementado en `reviewpulse_agent.py`, en Python. Dos clasificadores **Naive Bayes multinomiales** estiman por separado el tema y la polaridad a partir de palabras aprendidas de ejemplos etiquetados. La interfaz no llama a un LLM, no consulta una API y no extrae reseñas de Internet. Al crear cada instancia web, el prototipo carga ejemplos semilla incluidos en el código; por eso una reseña escrita en la interfaz no equivale a un entrenamiento con el corpus Trip-MAML.

    Los resultados numéricos de calidad del modelo —exactitud y macro-F1— se obtuvieron aparte, entrenando con `spanish_training.json` y evaluando en `spanish_test.json`. Para esa evaluación de referencia se reportaron 291 reseñas utilizables para entrenamiento y 125 para prueba; la exactitud conjunta fue 48 %. La polaridad derivada alcanzó 92,8 % de exactitud, mientras que el tema principal alcanzó 52 %. Estos resultados muestran que el modelo tiene dificultades para predecir el tema y para las clases minoritarias. Las etiquetas se derivaron por mayoría de las anotaciones por oración/aspecto, así que no son una medición idéntica a la tarea original multiaspecto.

    ### Qué demuestra y qué no demuestra la aplicación

    La web permite demostrar una ejecución en vivo, inspeccionar un caso normal y un rechazo esperado, correr pruebas funcionales y descargar evidencia con logs. La batería de pruebas acredita el comportamiento del ciclo; la evaluación separada con Trip-MAML es la evidencia para la calidad de clasificación. Los resultados bajos de tema y de exactitud conjunta no son fallas de la interfaz: indican límites del modelo actual y de la simplificación a una sola etiqueta por reseña.

    El prototipo tampoco está conectado a cuentas de hoteles, no guarda datos en una base persistente ni manda notificaciones reales. En el despliegue web, los archivos de ejecución se almacenan temporalmente y pueden borrarse al reiniciar el servicio. Descarga los ZIP y logs que necesites para conservar la evidencia.

    ### Tecnología y responsabilidades

    - **Python:** implementa percepción, clasificación, cálculo de confianza, alertas, simulador, pruebas y registro.
    - **Streamlit:** presenta los formularios, resultados, gráfico, tabla y opciones de descarga; no decide las clasificaciones.
    - **Trip-MAML:** corpus usado en la evaluación local; no se envía automáticamente desde esta aplicación web.
    - **Servicios externos y LLM:** no se utilizan.
    """)
    