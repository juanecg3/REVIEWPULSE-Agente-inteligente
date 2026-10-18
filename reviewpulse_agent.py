"""REVIEWPULSE-AGENT: prototipo local, sin servicios externos ni LLM."""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

TOPICS = ("limpieza", "servicio", "ubicacion", "precio", "habitacion", "otros")
SENTIMENTS = ("positivo", "neutral", "negativo")
TOKEN_RE = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)
ASPECT_MAP = {
    "ROOMS": "habitacion", "SLEEPQUALITY": "habitacion",
    "CLEANLINESS": "limpieza", "SERVICE": "servicio", "CHECKIN": "servicio",
    "VALUE": "precio", "LOCATION": "ubicacion",
    "OTHER": "otros", "FOOD": "otros", "BUILDING": "otros", "BUSINESS": "otros",
}
POLARITY_MAP = {"p": "positivo", "n": "negativo", "x": "neutral"}

def segment_surface_text(segment: str) -> str:
    """Quita POS, lema y polaridad del formato token/POS/lemma/sentimiento."""
    words = []
    for item in segment.split():
        surface = item.split("/", 1)[0]
        if surface:
            words.append(surface)
    text = " ".join(words)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\s+([)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    return text.strip()

def tripmaml_review_sample(record: dict) -> dict | None:
    """Reduce anotaciones multiaspecto a polaridad general y tema principal."""
    segments = record.get("segments", [])
    labels = record.get("segmentLabels", [])
    text = " ".join(segment_surface_text(s) for s in segments if s.strip())
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    topic_counts, sentiment_counts = Counter(), Counter()
    for sentence_labels in labels:
        if not isinstance(sentence_labels, dict):
            continue
        for aspect, polarity in sentence_labels.items():
            topic = ASPECT_MAP.get(aspect.upper())
            sentiment = POLARITY_MAP.get(str(polarity).lower())
            if not topic or not sentiment:
                continue
            topic_counts[topic] += 1
            sentiment_counts[sentiment] += 1
    if not text or not topic_counts or not sentiment_counts:
        return None
    # TOPICS/SENTIMENTS fijan un desempate determinista cuando hay empate.
    topic = max(TOPICS, key=lambda label: topic_counts[label])
    sentiment = max(SENTIMENTS, key=lambda label: sentiment_counts[label])
    return {
        "review_id": str(record.get("reviewId", "")),
        "text": text,
        "topic": topic,
        "sentiment": sentiment,
        "rating": record.get("ratingOverall"),
        "topic_counts": dict(topic_counts),
        "sentiment_counts": dict(sentiment_counts),
    }

def load_tripmaml(path: Path) -> list[dict]:
    """Lee el JSONL de Trip-MAML y conserva solo reseñas con texto y etiquetas útiles."""
    rows = []
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON inválido en {path}, línea {line_number}: {exc}") from exc
            sample = tripmaml_review_sample(record)
            if sample:
                rows.append(sample)
    return rows

# Etiquetas de demostración creadas para el prototipo; no son datos de Trip-MAML.
SEED_ROWS = [
    ("La habitación estaba limpia y el baño impecable", "limpieza", "positivo"),
    ("Todo muy limpio, sábanas frescas y ordenadas", "limpieza", "positivo"),
    ("El baño estaba sucio y encontramos polvo", "limpieza", "negativo"),
    ("La habitación tenía manchas y olía mal", "limpieza", "negativo"),
    ("La limpieza fue correcta, sin destacar", "limpieza", "neutral"),
    ("La habitación quedó limpia durante la estancia", "limpieza", "neutral"),
    ("El personal fue amable y atento", "servicio", "positivo"),
    ("Nos atendieron rápido y con mucha amabilidad", "servicio", "positivo"),
    ("El recepcionista fue grosero y no ayudó", "servicio", "negativo"),
    ("La atención fue lenta y poco amable", "servicio", "negativo"),
    ("El servicio estuvo bien, nada especial", "servicio", "neutral"),
    ("El personal respondió a nuestra solicitud", "servicio", "neutral"),
    ("El hotel está cerca del centro y bien ubicado", "ubicacion", "positivo"),
    ("Buena ubicación, cerca de restaurantes y transporte", "ubicacion", "positivo"),
    ("Está lejos de todo y la zona es ruidosa", "ubicacion", "negativo"),
    ("La ubicación fue incómoda y difícil para llegar", "ubicacion", "negativo"),
    ("La ubicación es normal para la ciudad", "ubicacion", "neutral"),
    ("El hotel queda en una zona residencial", "ubicacion", "neutral"),
    ("Buen precio para la calidad que ofrecen", "precio", "positivo"),
    ("La tarifa fue económica y valió la pena", "precio", "positivo"),
    ("Demasiado caro para una habitación tan básica", "precio", "negativo"),
    ("Cobran mucho por servicios de mala calidad", "precio", "negativo"),
    ("El precio estuvo dentro de lo esperado", "precio", "neutral"),
    ("La tarifa fue similar a otros hoteles", "precio", "neutral"),
    ("La habitación era amplia, cómoda y silenciosa", "habitacion", "positivo"),
    ("Dormimos muy bien, la cama era cómoda", "habitacion", "positivo"),
    ("La habitación era pequeña y la cama incómoda", "habitacion", "negativo"),
    ("El aire acondicionado no funcionaba en el cuarto", "habitacion", "negativo"),
    ("La habitación tenía tamaño y muebles estándar", "habitacion", "neutral"),
    ("El cuarto tenía una cama y un escritorio", "habitacion", "neutral"),
    ("El desayuno estuvo delicioso y variado", "otros", "positivo"),
    ("Disfrutamos mucho la piscina del hotel", "otros", "positivo"),
    ("El desayuno estaba frío y había poca variedad", "otros", "negativo"),
    ("La piscina estaba cerrada durante nuestra visita", "otros", "negativo"),
    ("El hotel tiene desayuno y estacionamiento", "otros", "neutral"),
    ("La estancia incluyó acceso a las áreas comunes", "otros", "neutral"),
]

PHRASES = {
    "limpieza": {
        "positivo": ["todo estaba limpio e impecable", "baño limpio y sábanas frescas", "habitación ordenada y sin polvo"],
        "neutral": ["la limpieza fue normal", "el baño estaba aceptable", "la habitación estaba ordenada"],
        "negativo": ["había suciedad y polvo", "el baño estaba sucio", "encontramos manchas y mal olor"],
    },
    "servicio": {
        "positivo": ["el personal fue amable y atento", "nos atendieron rápido", "la recepción nos ayudó mucho"],
        "neutral": ["la atención fue normal", "el personal respondió", "el servicio estuvo correcto"],
        "negativo": ["el personal fue grosero", "la atención fue lenta", "nadie nos ayudó con el problema"],
    },
    "ubicacion": {
        "positivo": ["muy cerca del centro", "bien ubicado junto al transporte", "la zona es agradable y segura"],
        "neutral": ["la ubicación es normal", "queda en una zona residencial", "la distancia fue aceptable"],
        "negativo": ["queda lejos de todo", "la zona era ruidosa", "fue difícil llegar al hotel"],
    },
    "precio": {
        "positivo": ["buen precio para la calidad", "la tarifa fue económica", "valió la pena lo que pagamos"],
        "neutral": ["el precio fue razonable", "la tarifa estuvo dentro de lo esperado", "costó como otros hoteles"],
        "negativo": ["demasiado caro para lo ofrecido", "la tarifa fue muy alta", "no valió lo que pagamos"],
    },
    "habitacion": {
        "positivo": ["habitación amplia y cómoda", "la cama era cómoda", "dormimos muy bien en el cuarto"],
        "neutral": ["habitación de tamaño normal", "el cuarto tenía muebles básicos", "la cama estuvo aceptable"],
        "negativo": ["la habitación era pequeña e incómoda", "la cama estaba en mal estado", "el aire no funcionaba en el cuarto"],
    },
    "otros": {
        "positivo": ["el desayuno estuvo delicioso", "disfrutamos mucho la piscina", "las áreas comunes estaban excelentes"],
        "neutral": ["el hotel ofrece desayuno", "hay estacionamiento disponible", "la estancia incluyó áreas comunes"],
        "negativo": ["el desayuno estaba frío", "la piscina estaba cerrada", "las áreas comunes estaban descuidadas"],
    },
}

class NaiveBayes:
    """Clasificador multinomial pequeño que puede actualizarse con feedback humano."""
    def __init__(self, labels: tuple[str, ...]):
        self.labels = labels
        self.docs = Counter()
        self.words = {label: Counter() for label in labels}
        self.vocabulary: set[str] = set()

    def learn(self, text: str, label: str) -> None:
        if label not in self.words:
            return
        tokens = TOKEN_RE.findall(text.lower())
        self.docs[label] += 1
        self.words[label].update(tokens)
        self.vocabulary.update(tokens)

    def predict(self, text: str) -> tuple[str, float, dict[str, float]]:
        tokens = TOKEN_RE.findall(text.lower())
        total_docs = sum(self.docs.values()) or 1
        vocab_size = max(len(self.vocabulary), 1)
        scores = {}
        for label in self.labels:
            denom = sum(self.words[label].values()) + vocab_size
            score = math.log((self.docs[label] + 1) / (total_docs + len(self.labels)))
            for token in tokens:
                score += math.log((self.words[label][token] + 1) / denom)
            scores[label] = score
        peak = max(scores.values())
        exp_scores = {label: math.exp(value - peak) for label, value in scores.items()}
        z = sum(exp_scores.values()) or 1
        probs = {label: value / z for label, value in exp_scores.items()}
        best = max(probs, key=probs.get)
        return best, probs[best], probs

class ReviewPulseAgent:
    """Percepción -> decisión (clasificación/reglas) -> acción (persistencia/reporte)."""
    def __init__(self, root: Path, confidence_threshold: float = 0.42,
                 include_seed: bool = True, load_feedback: bool = True):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_path = self.root / "execution.jsonl"
        self.feedback_path = self.root / "learned_feedback.csv"
        self.confidence_threshold = confidence_threshold
        self.polarity = NaiveBayes(SENTIMENTS)
        self.topic = NaiveBayes(TOPICS)
        if include_seed:
            for text, topic, sentiment in SEED_ROWS:
                self.polarity.learn(text, sentiment)
                self.topic.learn(text, topic)
        if load_feedback:
            self._load_feedback()

    def train_rows(self, rows: list[dict]) -> int:
        """Entrena desde datos etiquetados; no los guarda como feedback humano futuro."""
        count = 0
        for row in rows:
            if row.get("text") and row.get("topic") in TOPICS and row.get("sentiment") in SENTIMENTS:
                self.polarity.learn(row["text"], row["sentiment"])
                self.topic.learn(row["text"], row["topic"])
                count += 1
        return count

    def _load_feedback(self) -> None:
        if not self.feedback_path.exists():
            return
        with self.feedback_path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                text = row.get("text", "")
                if text:
                    self.polarity.learn(text, row.get("sentiment", ""))
                    self.topic.learn(text, row.get("topic", ""))

    def perceive(self, raw: dict) -> dict:
        """Valida y normaliza una percepción recibida del simulador o de un CSV."""
        text = " ".join(str(raw.get("text", "")).split())
        if not text:
            raise ValueError("La reseña no puede estar vacía")
        return {
            "review_id": str(raw.get("review_id", "unknown")),
            "text": text,
            "published_at": str(raw.get("published_at", datetime.now(timezone.utc).isoformat())),
            "source": str(raw.get("source", "simulador")),
            "rating": raw.get("rating"),
        }

    def decide(self, perception: dict) -> dict:
        sentiment, sent_conf, sent_probs = self.polarity.predict(perception["text"])
        topic, topic_conf, topic_probs = self.topic.predict(perception["text"])
        confidence = min(sent_conf, topic_conf)
        return {
            "sentiment": sentiment,
            "topic": topic,
            "confidence": round(confidence, 4),
            "sentiment_confidence": round(sent_conf, 4),
            "topic_confidence": round(topic_conf, 4),
            "sentiment_probabilities": {k: round(v, 4) for k, v in sent_probs.items()},
            "topic_probabilities": {k: round(v, 4) for k, v in topic_probs.items()},
            "needs_human_review": confidence < self.confidence_threshold,
            "model": "multinomial_naive_bayes_incremental_v1",
        }

    def act(self, perception: dict, decision: dict) -> dict:
        action = {
            "stored_prediction": True,
            "added_to_weekly_aggregate": True,
            "sent_to_human_review": decision["needs_human_review"],
        }
        self._log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "perception": perception,
            "decision": decision,
            "action": action,
        })
        return action

    def process(self, raw: dict) -> dict:
        try:
            perception = self.perceive(raw)
        except ValueError as exc:
            # Conserva la trazabilidad también cuando la entrada se rechaza antes
            # de que exista una clasificación.
            self._log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "perception": {
                    "review_id": str(raw.get("review_id", "unknown")),
                    "text": str(raw.get("text", "")),
                    "published_at": str(raw.get("published_at", "")),
                    "source": str(raw.get("source", "desconocida")),
                    "rating": raw.get("rating"),
                },
                "decision": {"error": str(exc)},
                "action": {"rejected": True, "reason": "entrada_invalida"},
            })
            raise
        decision = self.decide(perception)
        action = self.act(perception, decision)
        return {"perception": perception, "decision": decision, "action": action}

    def apply_feedback(self, feedback: list[dict]) -> int:
        """Aprende de correcciones confirmadas; deja persistida la memoria a largo plazo."""
        existing = self.feedback_path.exists()
        with self.feedback_path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["text", "topic", "sentiment"])
            if not existing:
                writer.writeheader()
            count = 0
            for row in feedback:
                text = " ".join(str(row.get("text", "")).split())
                topic, sentiment = row.get("topic"), row.get("sentiment")
                if text and topic in TOPICS and sentiment in SENTIMENTS:
                    writer.writerow({"text": text, "topic": topic, "sentiment": sentiment})
                    self.topic.learn(text, topic)
                    self.polarity.learn(text, sentiment)
                    count += 1
        self._log({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "perception": {"source": "retroalimentacion_humana", "examples": len(feedback)},
            "decision": {"operation": "actualizacion_incremental"},
            "action": {"learned_examples": count, "memory_file": str(self.feedback_path)},
        })
        return count

    def weekly_reports(self, results: list[dict], min_reviews: int = 3) -> list[dict]:
        weeks = defaultdict(list)
        for result in results:
            dt = datetime.fromisoformat(result["perception"]["published_at"].replace("Z", "+00:00"))
            iso = dt.isocalendar()
            weeks[f"{iso.year}-W{iso.week:02d}"].append(result)
        reports = []
        previous_rates = []
        for week in sorted(weeks):
            rows = weeks[week]
            negative = sum(r["decision"]["sentiment"] == "negativo" for r in rows)
            rate = negative / len(rows)
            baseline = (sum(previous_rates) / len(previous_rates)) if previous_rates else None
            threshold = (baseline + 0.20) if baseline is not None else None
            alert = len(rows) >= min_reviews and threshold is not None and rate > threshold
            topic_counts = Counter(r["decision"]["topic"] for r in rows)
            report = {
                "week": week,
                "review_count": len(rows),
                "negative_count": negative,
                "negative_rate": round(rate, 4),
                "topic_counts": dict(topic_counts),
                "alert": alert,
                "alert_reason": (f"negatividad {rate:.0%} supera el umbral {threshold:.0%} (línea base {baseline:.0%})" if alert else None),
                "line_base": round(baseline, 4) if baseline is not None else None,
                "alert_threshold": round(threshold, 4) if threshold is not None else None,
                "limitations": "La demo usa reseñas simuladas; la alerta no representa un hotel real.",
            }
            reports.append(report)
            self._log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "perception": {"source": "memoria_semanal", "week": week, "review_count": len(rows)},
                "decision": {"negative_rate": rate, "baseline": report["line_base"], "alert_threshold": report["alert_threshold"], "alert": alert},
                "action": {"weekly_report": report, "notification_emitted": alert},
            })
            previous_rates.append(rate)
        return reports

    def _log(self, record: dict) -> None:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

class StochasticReviewEnvironment:
    """Simula reseñas; el tema/sentimiento y el ruido se muestrean aleatoriamente."""
    def __init__(self, seed: int = 42, start: datetime | None = None):
        self.rng = random.Random(seed)
        # Fecha simulada fija para que la misma semilla reproduzca también las fechas.
        self.start = start or datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.seed = seed

    def generate(self, count: int = 60) -> list[dict]:
        reviews = []
        topics = tuple(PHRASES)
        for i in range(count):
            day = i % 28
            # Estocasticidad: semana final simula un aumento de negatividad; se agrega ruido.
            negative_probability = 0.22 if day < 21 else 0.62
            draw = self.rng.random()
            if draw < negative_probability:
                sentiment = "negativo"
            elif draw < negative_probability + 0.14:
                sentiment = "neutral"
            else:
                sentiment = "positivo"
            topic = self.rng.choice(topics)
            text = self.rng.choice(PHRASES[topic][sentiment])
            if self.rng.random() < 0.12:
                text += " " + self.rng.choice(["y el desayuno estuvo bien", "aunque el personal fue amable", "durante nuestra visita"])
            published = self.start + timedelta(days=day, minutes=self.rng.randrange(0, 1440))
            reviews.append({
                "review_id": f"sim-{self.seed}-{i+1:04d}",
                "text": text,
                "published_at": published.isoformat(),
                "source": "simulador_estocastico",
                "rating": self.rng.randint(1, 5),
                "simulation_truth": {"topic": topic, "sentiment": sentiment},
            })
        return reviews

def accuracy(gold: list[str], predicted: list[str]) -> float:
    if not gold:
        return 0.0
    return sum(a == b for a, b in zip(gold, predicted)) / len(gold)

def macro_f1(gold: list[str], predicted: list[str], labels: tuple[str, ...]) -> float:
    scores = []
    for label in labels:
        tp = sum(g == label and p == label for g, p in zip(gold, predicted))
        fp = sum(g != label and p == label for g, p in zip(gold, predicted))
        fn = sum(g == label and p != label for g, p in zip(gold, predicted))
        denominator = 2 * tp + fp + fn
        scores.append((2 * tp / denominator) if denominator else 0.0)
    return sum(scores) / len(scores)

def evaluate_tripmaml(agent: ReviewPulseAgent, rows: list[dict]) -> dict:
    gold_topics, pred_topics = [], []
    gold_sentiments, pred_sentiments = [], []
    joint_correct = 0
    for row in rows:
        result = agent.process({
            "review_id": row["review_id"], "text": row["text"], "rating": row.get("rating"),
            "source": "Trip-MAML-test",
        })
        decision = result["decision"]
        gold_topics.append(row["topic"])
        pred_topics.append(decision["topic"])
        gold_sentiments.append(row["sentiment"])
        pred_sentiments.append(decision["sentiment"])
        joint_correct += decision["topic"] == row["topic"] and decision["sentiment"] == row["sentiment"]
    return {
        "source": "Trip-MAML spanish_test.json",
        "test_reviews": len(rows),
        "topic_accuracy": round(accuracy(gold_topics, pred_topics), 4),
        "topic_macro_f1": round(macro_f1(gold_topics, pred_topics, TOPICS), 4),
        "sentiment_accuracy": round(accuracy(gold_sentiments, pred_sentiments), 4),
        "sentiment_macro_f1": round(macro_f1(gold_sentiments, pred_sentiments, SENTIMENTS), 4),
        "joint_accuracy": round(joint_correct / len(rows), 4) if rows else 0.0,
        "label_definition": "Polaridad y tema derivados por mayoría de las anotaciones por oración; los empates se resuelven en el orden fijo de las clases.",
        "warning": "El conjunto de prueba se usa solo para evaluar; esta exactitud no equivale a la métrica del diseño si su protocolo de etiquetas difiere.",
    }

def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta la demo del REVIEWPULSE-AGENT")
    parser.add_argument("--count", type=int, default=60, help="número de reseñas simuladas")
    parser.add_argument("--seed", type=int, default=42, help="semilla para reproducir el simulador")
    parser.add_argument("--out", default="run", help="carpeta para logs y reportes")
    parser.add_argument("--feedback", help="CSV opcional con text,topic,sentiment corregidos por una persona")
    parser.add_argument("--tripmaml-train", help="ruta a spanish_training.json (JSONL)")
    parser.add_argument("--tripmaml-test", help="ruta a spanish_test.json (JSONL)")
    args = parser.parse_args()
    root = Path(args.out)
    if bool(args.tripmaml_train) != bool(args.tripmaml_test):
        parser.error("--tripmaml-train y --tripmaml-test deben usarse juntos")
    tripmaml_mode = bool(args.tripmaml_train and args.tripmaml_test)
    agent = ReviewPulseAgent(root, include_seed=not tripmaml_mode, load_feedback=not tripmaml_mode)
    tripmaml_metrics = None
    if tripmaml_mode:
        train_rows = load_tripmaml(Path(args.tripmaml_train))
        test_rows = load_tripmaml(Path(args.tripmaml_test))
        train_ids = {row["review_id"] for row in train_rows}
        test_ids = {row["review_id"] for row in test_rows}
        overlap = train_ids & test_ids
        if overlap:
            parser.error(f"Hay {len(overlap)} reviewId repetidos entre entrenamiento y prueba; se detiene para evitar fuga de datos")
        learned = agent.train_rows(train_rows)
        tripmaml_metrics = evaluate_tripmaml(agent, test_rows)
        tripmaml_metrics["training_reviews"] = learned
        tripmaml_metrics["skipped_train_records"] = max(0, sum(1 for _ in Path(args.tripmaml_train).open(encoding="utf-8-sig") if _.strip()) - learned)
        tripmaml_metrics["verified_train_test_id_overlap"] = len(overlap)
        (root / "tripmaml_evaluation.json").write_text(json.dumps(tripmaml_metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.feedback:
        with Path(args.feedback).open(encoding="utf-8-sig", newline="") as f:
            feedback_rows = list(csv.DictReader(f))
        learned = agent.apply_feedback(feedback_rows)
        print(f"Ejemplos de feedback humano incorporados: {learned}")
    results, reports = [], []
    if args.count > 0:
        env = StochasticReviewEnvironment(seed=args.seed)
        raw_reviews = env.generate(args.count)
        results = [agent.process({k: v for k, v in raw.items() if k != "simulation_truth"}) for raw in raw_reviews]
        reports = agent.weekly_reports(results)
    output = {
        "agent": "REVIEWPULSE-AGENT",
        "agent_type": "agente de aprendizaje supervisado con actualización incremental por feedback humano",
        "simulation_seed": args.seed,
        "processed_reviews": len(results),
        "tripmaml_evaluation": tripmaml_metrics,
        "needs_human_review": sum(x["decision"]["needs_human_review"] for x in results),
        "weekly_reports": reports,
        "log_file": str(agent.log_path.resolve()),
    }
    (root / "summary.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
