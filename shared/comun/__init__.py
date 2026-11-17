"""Paquete compartido por todos los servicios.

Cada módulo resuelve una preocupación transversal:

- config:         variables de entorno
- contexto:       datos de la petición actual (correlation id, IP)
- db / modelos:   conexión a la base única y modelos SQLAlchemy
- seguridad:      JWT y revisión de roles
- historial:      registrar un cambio como evento (patrón outbox)
- mensajeria:     publicar y consumir eventos en RabbitMQ
- consul:         registro y descubrimiento de servicios
- observabilidad: logs JSON, trazas OpenTelemetry y métricas Prometheus
- recursos:       rutas CRUD genéricas con historial y borrado lógico
- app:            fábrica de aplicaciones FastAPI con todo lo anterior
"""
